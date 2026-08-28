"""Apply-phase orchestration for AI Auto-Fix (see docs/AI_AUTOFIX_DESIGN.md).

Entry point ai_remediation_queue_service invokes after claiming a kind="apply" RemediationJob
(enqueued only by the human-approval endpoint). Deterministic, NO LLM: clone the repo, run the
scanner baseline, apply the already-approved patches by exact-match, enforce the scope allowlist,
re-scan to confirm the findings cleared with no new >=medium findings, and only then create a
branch + commit + push + open a PR. Every unsafe condition -> review_state="manual_review" with a
specific reason; nothing is ever force-written. The workspace is always cleaned up.

A job carries a BATCH of approved proposals (`proposal_ids`) -- one batch, one branch, one PR --
so a 40-finding scan no longer costs 40 PRs, 40 clones and 80 scanner runs. A batch is scoped to
one scan, which is what makes it safe: same repo, same base branch, by construction. A patch that
can't be applied or fails the re-scan gate is dropped from the batch, not fatal to it. The
single-proposal approve route is simply a batch of one. See docs/AUTOFIX_BATCH_PR.md.
"""

import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog

from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.finding import Finding
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.models.user import User
from app.services import (
    audit_service,
    connection_service,
    fix_pattern_service,
    git_workspace,
    project_repo_service,
    remediation_brief_service,
    remediation_settings_service,
)
from app.services.repo_write import RepoWriteError
from app.services.repo_write import azure_devops as ado_write
from app.services.repo_write import github as gh_write

logger = structlog.get_logger(__name__)

# Fallback default; the effective set is admin-configurable via RemediationSettings
# (remediation_settings_service) and read per-apply in _apply.
_BLOCKING_SEVERITIES = {"critical", "high", "medium"}


class _ManualReview(Exception):
    """A condition that makes an automatic write unsafe. Resolves the proposal to manual_review
    with this reason -- never fails hard, never force-writes."""


async def _resolve_credential(repo: ProjectRepo, approver_user_id: str | None):
    """Returns (token, git_scheme, rest_scheme, source). Prefers a ProjectRepo PAT; else the
    APPROVER's own OAuth connection for the repo's provider (IDOR-scoped). Raises _ManualReview
    with an actionable reason when no usable write credential exists."""
    pat = project_repo_service.decrypt_pat(repo)
    if pat:
        # PATs authenticate git-over-HTTPS and the Azure REST call via Basic.
        return pat, "basic", "basic", "pat"

    if not approver_user_id:
        raise _ManualReview("No write credential: this repo was connected without a token.")
    user = await User.get(approver_user_id)
    if user is None:
        raise _ManualReview("Approver account not found; re-approve to apply.")
    # get_own_connection_or_404 raises HTTPException(404) if absent; translate to manual_review.
    try:
        conn = await connection_service.get_own_connection_or_404(user, repo.provider)
    except Exception:
        raise _ManualReview(
            f"No {repo.provider} connection for the approver. Connect the repo (with write access) and re-approve."
        )
    if repo.provider == "azure_devops" and "vso.code_write" not in (conn.scope or ""):
        raise _ManualReview("Reconnect Azure DevOps to grant write access (vso.code_write), then re-approve.")
    token, provider = await connection_service.get_decrypted_token(str(conn.id), user)
    # GitHub OAuth token pushes via Basic; Azure AAD token via Bearer (git + REST).
    git_scheme = "basic" if provider == "github" else "bearer"
    rest_scheme = "bearer" if provider == "azure_devops" else "basic"
    return token, git_scheme, rest_scheme, "oauth"


def _apply_patch(workdir: str, file_path: str, original_code: str, patched_code: str) -> None:
    target = (Path(workdir) / file_path).resolve()
    root = Path(workdir).resolve()
    if root not in target.parents and target != root:
        raise _ManualReview("Patch target path escapes the repository.")
    if not target.is_file():
        raise _ManualReview(f"File not found in the repository: {file_path}")
    text = target.read_text(encoding="utf-8", errors="replace")
    count = text.count(original_code)
    if count == 0:
        raise _ManualReview("Source changed since the scan; regenerate the proposal.")
    if count > 1:
        raise _ManualReview("The original code is not unique in the file; cannot apply deterministically.")
    target.write_text(text.replace(original_code, patched_code, 1), encoding="utf-8")


def _fingerprints(report) -> set[str]:
    return {f.fingerprint for f in report.findings if f.fingerprint}


async def _push_with_recovery(workdir, branch_name, token, git_scheme) -> str:
    """Push the branch; recover once from a shallow-clone rejection. Returns the final branch name
    (unchanged here; collision handling regenerates upstream). Raises _ManualReview on a write-perm
    denial or an unrecoverable push error."""
    rc, _out, err = await git_workspace.git(
        ["push", "origin", f"HEAD:refs/heads/{branch_name}"], workdir, token, git_scheme, timeout=180
    )
    if rc == 0:
        return branch_name
    low = err.lower()
    if "shallow update not allowed" in low or "shallow" in low:
        rc2, _o2, _e2 = await git_workspace.git(["fetch", "--unshallow", "origin"], workdir, token, git_scheme, timeout=300)
        rc, _out, err = await git_workspace.git(
            ["push", "origin", f"HEAD:refs/heads/{branch_name}"], workdir, token, git_scheme, timeout=180
        )
        if rc == 0:
            return branch_name
        low = err.lower()
    if any(t in low for t in ("403", "permission", "denied", "authentication", "forbidden", "not authorized")):
        raise _ManualReview(
            "The repository token lacks write permission. Provide a PAT with write access "
            "(GitHub 'repo' / Azure 'Code Read & Write') or reconnect OAuth with write scope."
        )
    raise _ManualReview(f"Could not push the fix branch: {err[:300]}")


async def _open_pr(repo: ProjectRepo, token, rest_scheme, branch_name, base, title, body) -> dict:
    if repo.provider == "github":
        owner, _, name = repo.repo_full_name.partition("/")
        return await gh_write.open_pull_request(token, owner, name, head=branch_name, base=base, title=title, body=body)
    # azure_devops
    org = repo.organization
    project = repo.ado_project or repo.repo_full_name.split("/")[0]
    repo_name = repo.repo_full_name.split("/")[-1]
    repo_id = await ado_write.resolve_repo_id(token, rest_scheme, org, project, repo_name)
    return await ado_write.open_pull_request(
        token, rest_scheme, org, project, repo_id,
        source_branch=branch_name, target_branch=base, title=title, description=body,
    )


async def _save(proposal: AIFixProposal) -> None:
    proposal.updated_at = datetime.now(timezone.utc)
    await proposal.save()


@dataclass
class _Item:
    """One proposal's slot in the batch, plus the finding its fingerprint gate needs."""

    proposal: AIFixProposal
    finding: Finding


async def _drop(
    proposal: AIFixProposal,
    finding: Finding | None,
    reason: str,
    job: RemediationJob,
    log: list[tuple[AIFixProposal, "Finding | None", str]],
) -> None:
    """Resolve ONE proposal out of the batch without failing the rest. This is the whole point of
    batching: a drifted source file or a patch that fails the re-scan gate must not cost the other
    fixes their PR.

    Every drop is appended to `log`, which is what the PR body's summary table renders. A fix left
    out silently is the same auditability hole as a PR per finding, just quieter."""
    proposal.review_state = "manual_review"
    proposal.manual_review_reason = reason
    await _save(proposal)
    log.append((proposal, finding, reason))
    await audit_service.record(
        "AI Fix Marked Manual Review", actor_user_id=job.approver_user_id,
        project_id=proposal.project_id, target_type="ai_fix_proposal",
        target_id=str(proposal.id), metadata={"reason": reason, "batch_job_id": str(job.id)},
    )


def _blame(report, new_fps: set[str], blocking: set[str], applied: list[str]) -> tuple[set[str], int]:
    """Attribute new blocking findings to the patched file they landed in.

    Returns (blamed file paths, count that matched NO patched file). An unattributable one means
    a patch broke a file it didn't touch, so there is no safe subset to retry -- the caller aborts
    the whole batch rather than guessing. Suffix match because the scanner reports paths relative
    to its own root, which need not be the repo-relative form the proposal carries."""
    blamed: set[str] = set()
    unattributed = 0
    for f in report.findings:
        if f.fingerprint not in new_fps or (f.severity or "").lower() not in blocking:
            continue
        loc = getattr(f, "location", None)
        path = ((getattr(loc, "file", "") or "") if loc is not None else "").replace("\\", "/")
        hit = next((a for a in applied if path == a or path.endswith("/" + a)), None)
        if hit:
            blamed.add(hit)
        else:
            unattributed += 1
    return blamed, unattributed


async def _stage_patches(workdir: str, items: list[_Item], job: RemediationJob, log: list) -> list[_Item]:
    """Write every patch into the shared worktree, in order. A patch that can't be applied
    deterministically drops just its own proposal."""
    applied: list[_Item] = []
    for it in items:
        try:
            _apply_patch(workdir, it.proposal.file_path, it.proposal.original_code, it.proposal.patched_code)
        except _ManualReview as mr:
            await _drop(it.proposal, it.finding, str(mr), job, log)
            continue
        applied.append(it)
    return applied


async def _rescan_and_judge(
    workdir: str, items: list[_Item], baseline_fps: set[str], blocking: set[str]
) -> tuple[list[_Item], list[tuple[_Item, str]], str | None]:
    """One scanner run over the combined diff. Returns (survivors, dropped, fatal_reason).

    Stamps each item's `validation` artifact, so a reviewer sees the same evidence a
    single-proposal apply produced. Does not touch review_state -- the caller decides, because
    a first-round drop is retried before it becomes a verdict."""
    rc, changed_out, _err = await git_workspace.git(["diff", "--name-only"], workdir)
    changed = sorted(line.strip() for line in changed_out.splitlines() if line.strip())
    expected = sorted({it.proposal.file_path for it in items})
    if changed != expected:
        return [], [], f"The patches modified unexpected files: {changed or 'none'}."

    post_report, _ = await git_workspace.run_scanner(workdir)
    post_fps = _fingerprints(post_report)
    new_fps = post_fps - baseline_fps
    blamed, unattributed = _blame(post_report, new_fps, blocking, expected)
    ran_at = datetime.now(timezone.utc).isoformat()
    sev_label = "/".join(sorted(blocking))

    survivors: list[_Item] = []
    dropped: list[tuple[_Item, str]] = []
    for it in items:
        cleared = it.finding.fingerprint not in post_fps
        it.proposal.validation = {
            "scope_ok": True,
            "target_cleared": cleared,
            "new_finding_count": len(new_fps),
            "new_finding_fingerprints": sorted(new_fps)[:50],
            "baseline_count": len(baseline_fps),
            "post_count": len(post_fps),
            "scanner_version": post_report.scanner_version,
            "ran_at": ran_at,
            "batch_size": len(items),
        }
        if not cleared:
            dropped.append((it, "The fix did not clear the finding on re-scan."))
        elif it.proposal.file_path in blamed:
            dropped.append((it, f"The fix introduced new {sev_label} finding(s) in {it.proposal.file_path}."))
        else:
            survivors.append(it)

    if unattributed:
        return [], [], (
            f"The fixes introduced {unattributed} new {sev_label} finding(s) outside the patched files; "
            "apply them individually to find the cause."
        )
    return survivors, dropped, None


def _pr_summary_table(survivors: list[_Item], dropped: list[tuple[AIFixProposal, "Finding | None", str]]) -> str:
    """Per-finding traceability inside the batch PR: what shipped, what didn't, and why. A reviewer
    must not have to leave the PR to learn that three of the scan's fixes were left out."""
    rows = ["| Finding | Severity | File | Status |", "| --- | --- | --- | --- |"]
    for it in survivors:
        f = it.finding
        rows.append(
            f"| {f.rule_name or f.rule_id or 'Finding'} | {f.severity or '—'} | `{it.proposal.file_path}` | included |"
        )
    for proposal, f, reason in dropped:
        name = (f.rule_name or f.rule_id or "Finding") if f else "Finding"
        rows.append(
            f"| {name} | {(f.severity if f else None) or '—'} | `{proposal.file_path or '—'}` | skipped — {reason} |"
        )
    return "\n".join(rows)


async def _apply(job: RemediationJob, proposals: list[AIFixProposal]) -> None:
    """Apply a batch of approved proposals as ONE branch, ONE commit, ONE PR.

    A batch is scoped to a single scan, so every proposal in it already shares a repository and a
    base branch -- the compatibility signals worth grouping on are structural, not computed. Patch
    conflict is the one signal metadata can't predict, so it isn't predicted: patches are applied
    and observed, and whatever fails the gate is dropped from the batch instead of failing it.
    See docs/AUTOFIX_BATCH_PR.md."""
    # Idempotent: a concurrent/duplicate approve must never open a second PR (defends the
    # check-then-insert window in the approve endpoint).
    pending = [p for p in proposals if not (p.review_state == "pr_open" and p.pr_url)]
    if not pending:
        return
    for p in pending:
        p.review_state = "applying"
        await _save(p)

    # Every proposal left out of the PR, with why -- rendered into the PR body's summary table.
    left_out: list[tuple[AIFixProposal, Finding | None, str]] = []
    items: list[_Item] = []
    for p in pending:
        if not (p.can_fix and p.original_code and p.patched_code and p.file_path):
            await _drop(p, None, "Proposal has no applicable patch.", job, left_out)
            continue
        finding = await Finding.get(p.finding_id)
        if finding is None or not finding.fingerprint:
            await _drop(p, finding, "Finding is missing or has no fingerprint; cannot validate the fix.", job, left_out)
            continue
        items.append(_Item(p, finding))
    if not items:
        return

    lead = items[0].proposal
    try:
        scan = await Scan.get(lead.scan_id)
    except Exception:
        scan = None
    repo = await ProjectRepo.get(scan.project_repo_id) if scan and scan.project_repo_id else None
    if scan is None or not scan.repo_url or repo is None:
        raise _ManualReview("No connected repository to open a PR against.")
    if repo.provider not in ("github", "azure_devops"):
        raise _ManualReview(f"Auto-PR is not supported for provider {repo.provider!r}.")

    token, git_scheme, rest_scheme, source = await _resolve_credential(repo, job.approver_user_id)
    base = lead.base_branch or repo.selected_branch or (scan.branch if scan else None) or "main"

    workdir = tempfile.mkdtemp(prefix="zs-remediate-", dir=git_workspace.workdir_root())
    try:
        git_workspace.validate_repo_url(scan.repo_url)
        await git_workspace.clone_repo(scan.repo_url, base, workdir, token, git_scheme)

        # One clone, one baseline, for the whole batch -- the per-proposal path re-cloned and
        # re-scanned the same tree once per finding.
        baseline_report, _ = await git_workspace.run_scanner(workdir)
        baseline_fps = _fingerprints(baseline_report)
        live: list[_Item] = []
        for it in items:
            if it.finding.fingerprint not in baseline_fps:
                await _drop(it.proposal, it.finding,
                            "The finding no longer reproduces on a fresh clone; the source may have changed.",
                            job, left_out)
            else:
                live.append(it)
        if not live:
            return

        cfg = await remediation_settings_service.get_settings()
        blocking = {s.lower() for s in cfg.blocking_severities} or _BLOCKING_SEVERITIES

        live = await _stage_patches(workdir, live, job, left_out)
        if not live:
            return
        survivors, dropped, fatal = await _rescan_and_judge(workdir, live, baseline_fps, blocking)
        if fatal:
            raise _ManualReview(fatal)
        if dropped:
            # Bounded retry: reset the worktree, re-apply only the fixes that passed, re-scan once.
            # Never loops -- if the survivor set is still dirty the batch is unsafe as a unit.
            if not survivors:
                for it, reason in dropped:
                    await _drop(it.proposal, it.finding, reason, job, left_out)
                return
            await git_workspace.git(["checkout", "--", "."], workdir)
            retry = await _stage_patches(workdir, survivors, job, left_out)
            if not retry:
                return
            survivors, again, fatal = await _rescan_and_judge(workdir, retry, baseline_fps, blocking)
            if fatal or again:
                raise _ManualReview(
                    f"Validation still failed after dropping {len(dropped)} fix(es); "
                    "apply these fixes individually."
                )
            for it, reason in dropped:
                await _drop(it.proposal, it.finding, reason, job, left_out)

        for it in survivors:
            it.proposal.review_state = "validated"
            await _save(it.proposal)
            await audit_service.record(
                "AI Fix Validation Passed", actor_user_id=job.approver_user_id,
                project_id=it.proposal.project_id, target_type="ai_fix_proposal",
                target_id=str(it.proposal.id),
                metadata={"target_cleared": True, "batch_size": len(survivors)},
            )

        first = survivors[0]
        if len(survivors) == 1:
            branch_name = first.proposal.branch_name or f"zerostrike/fix-{first.proposal.finding_id[:8]}-{uuid.uuid4().hex[:8]}"
        else:
            branch_name = first.proposal.branch_name or f"zerostrike/fix-batch-{lead.scan_id[:8]}-{uuid.uuid4().hex[:8]}"
        # Never commit onto the base/default branch. If the (owner-overridable) branch name equals
        # base, `git checkout -b` would fail and the commit would land on base and fast-forward-push
        # straight to it -- defeating the PR-only invariant. Reject up front and verify the checkout.
        if branch_name == base:
            raise _ManualReview("The fix branch name must differ from the base branch.")
        rc, _o, err = await git_workspace.git(["rev-parse", base], workdir)
        base_sha = _o.strip() if rc == 0 else None
        rc, _co, cberr = await git_workspace.git(["checkout", "-b", branch_name], workdir)
        if rc != 0:
            raise _ManualReview(f"Could not create the fix branch {branch_name!r}: {cberr[:200]}")
        for it in survivors:
            rc, _ao, aerr = await git_workspace.git(["add", "--", it.proposal.file_path], workdir)
            if rc != 0:
                raise _ManualReview(f"Could not stage the patch: {aerr[:200]}")

        rules = [it.finding.rule_name or "security finding" for it in survivors]
        # Commit/PR use the "zero-strike/security fix: <name>" convention so teammates can spot
        # ZeroStrike-authored security fixes at a glance in git history / the PR list.
        if len(survivors) == 1:
            title = f"zero-strike/security fix: {rules[0]}"
            commit_msg = (
                f"{title}\n\n"
                f"Fixes {rules[0]} in {first.proposal.file_path}. ZeroStrike AI Auto-Fix (human-approved). "
                f"{first.proposal.explanation or ''}"
            ).strip()
        else:
            title = f"zero-strike/security fix: {len(survivors)} findings"
            body_lines = "\n".join(f"- {r} ({it.proposal.file_path})" for r, it in zip(rules, survivors))
            commit_msg = f"{title}\n\n{body_lines}\n\nZeroStrike AI Auto-Fix (human-approved)."
        rc, _o, cerr = await git_workspace.git(
            ["-c", "user.name=ZeroStrike Bot", "-c", "user.email=noreply@zerostrike.dev", "commit", "-m", commit_msg],
            workdir,
        )
        if rc != 0:
            raise _ManualReview(f"Could not commit the patch: {cerr[:300]}")
        rc, sha_out, _e = await git_workspace.git(["rev-parse", "HEAD"], workdir)
        commit_sha = sha_out.strip() if rc == 0 else None

        branch_name = await _push_with_recovery(workdir, branch_name, token, git_scheme)
        for it in survivors:
            await audit_service.record(
                "AI Fix Branch Pushed", actor_user_id=job.approver_user_id,
                project_id=it.proposal.project_id, target_type="ai_fix_proposal",
                target_id=str(it.proposal.id), metadata={"branch": branch_name, "commit": commit_sha},
            )

        # Same renderer as the downloadable remediation brief (one definition of "how we describe a
        # fix"), minus the diff -- the PR already *is* the diff. proposal.validation is set above,
        # so the re-scan evidence lands in the description a reviewer reads first.
        sections = [
            remediation_brief_service.render_proposal_section(it.proposal, it.finding, include_diff=False, heading_level=2)
            for it in survivors
        ]
        body = "\n".join(
            [
                "AI-generated fix"
                + ("es" if len(survivors) > 1 else "")
                + ", reviewed and approved by a human before this PR was opened.",
                "",
                _pr_summary_table(survivors, left_out),
                "",
                *sections,
                "",
                "_Review required before merge._",
            ]
        )
        try:
            pr = await _open_pr(repo, token, rest_scheme, branch_name, base, title, body)
        except RepoWriteError as exc:
            raise _ManualReview(str(exc))

        for it in survivors:
            p = it.proposal
            p.review_state = "pr_open"
            p.status = "applied"
            p.branch_name = branch_name
            p.commit_sha = commit_sha
            p.base_branch = base
            p.base_commit_sha = base_sha
            p.pr_url = pr["pr_url"]
            p.pr_number = pr["pr_number"]
            p.pr_provider = repo.provider
            await _save(p)
            await audit_service.record(
                "AI Fix PR Opened", actor_user_id=job.approver_user_id, project_id=p.project_id,
                target_type="ai_fix_proposal", target_id=str(p.id),
                metadata={"pr_url": pr["pr_url"], "pr_number": pr["pr_number"], "branch": branch_name,
                          "base": base, "credential": source, "batch_size": len(survivors)},
            )
            # Remember it: this patch cleared the scanner re-scan gate AND a human approved it, so
            # it's the strongest example available for the next occurrence of this rule in this
            # project. Best-effort by contract -- fix_pattern_service swallows its own errors.
            await fix_pattern_service.record(p, it.finding, "pr_open")
    except _ManualReview:
        raise
    except Exception as exc:
        # Scrub the write token from any unexpected error before it propagates to the proposal/job.
        raise RuntimeError(git_workspace.sanitize(str(exc), token)) from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def _load_batch(job: RemediationJob) -> list[AIFixProposal]:
    """`proposal_ids or [proposal_id]` -- apply jobs written before batching set only the singular
    field, and they must keep running."""
    ids = job.proposal_ids or ([job.proposal_id] if job.proposal_id else [])
    loaded = [await AIFixProposal.get(pid) for pid in ids]
    return [p for p in loaded if p is not None]


async def run_job(job: RemediationJob) -> None:
    start = datetime.now(timezone.utc)
    job.status = "running"
    job.started_at = start
    job.updated_at = start
    await job.save()
    structlog.contextvars.bind_contextvars(trace_id=job.trace_id, remediation_job_id=str(job.id))

    proposals = await _load_batch(job)
    if not proposals:
        job.status = "failed"
        job.error_message = "Proposal not found"
        job.completed_at = datetime.now(timezone.utc)
        await job.save()
        structlog.contextvars.clear_contextvars()
        return

    # Only proposals still mid-flight take a batch-wide verdict; anything _drop() already resolved
    # keeps its own, more specific reason. "validated" counts as mid-flight: the re-scan gate passed
    # but the branch/push/PR can still fail, and that verdict must land on the proposal.
    def in_flight() -> list[AIFixProposal]:
        return [p for p in proposals if p.review_state in ("approved", "applying", "validated")]

    try:
        await _apply(job, proposals)
    except _ManualReview as mr:
        for proposal in in_flight():
            proposal.review_state = "manual_review"
            proposal.manual_review_reason = str(mr)
            await _save(proposal)
            await audit_service.record(
                "AI Fix Marked Manual Review", actor_user_id=job.approver_user_id,
                project_id=proposal.project_id, target_type="ai_fix_proposal",
                target_id=str(proposal.id), metadata={"reason": str(mr)},
            )
    except Exception as exc:
        logger.exception("remediation apply job failed", job_id=str(job.id))
        reason = git_workspace.sanitize(str(exc), None)[:1000]
        stuck = in_flight()
        for proposal in stuck:
            proposal.review_state = "failed"
            proposal.failure_reason = reason
            await _save(proposal)
        job.status = "failed"
        job.error_message = str(exc)[:2000]
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        await job.save()
        await audit_service.record(
            "AI Fix Failed", actor_user_id=job.approver_user_id, project_id=job.project_id,
            target_type="remediation_job", target_id=str(job.id), metadata={"error": str(exc)[:500]},
        )
        from app.services import notification_service

        # One notification per batch, not per proposal -- N failure toasts for one failed write
        # is the same flaw this change exists to remove.
        await notification_service.notify(
            "autofix.apply_failed",
            project_id=job.project_id,
            title="Auto-fix could not be applied",
            body=reason or "See the fix's failure detail.",
            link=f"/projects/{job.project_id}/auto-fix/{job.scan_id}",
            severity="error",
        )
        structlog.contextvars.clear_contextvars()
        return

    now = datetime.now(timezone.utc)
    job.status = "completed"
    job.completed_at = now
    job.updated_at = now
    await job.save()
    structlog.contextvars.clear_contextvars()

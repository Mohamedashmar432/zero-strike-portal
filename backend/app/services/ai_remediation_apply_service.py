"""Apply-phase orchestration for AI Auto-Fix (see docs/AI_AUTOFIX_DESIGN.md).

Entry point ai_remediation_queue_service invokes after claiming a kind="apply" RemediationJob
(enqueued only by the human-approval endpoint). Deterministic, NO LLM: clone the repo, run the
scanner baseline, apply the already-approved patch by exact-match, enforce the scope allowlist,
re-scan to confirm the finding cleared with no new >=medium findings, and only then create a
branch + commit + push + open a PR. Every unsafe condition -> review_state="manual_review" with a
specific reason; nothing is ever force-written. The workspace is always cleaned up.
"""

import shutil
import tempfile
import uuid
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


def _new_blocking(report, new_fps: set[str], blocking_severities: set[str]) -> int:
    return sum(
        1
        for f in report.findings
        if f.fingerprint in new_fps and (f.severity or "").lower() in blocking_severities
    )


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


async def _apply(job: RemediationJob, proposal: AIFixProposal) -> None:
    # Idempotent: a concurrent/duplicate approve must never open a second PR (defends the
    # check-then-insert window in the approve endpoint).
    if proposal.review_state == "pr_open" and proposal.pr_url:
        return
    proposal.review_state = "applying"
    await _save(proposal)

    if not (proposal.can_fix and proposal.original_code and proposal.patched_code and proposal.file_path):
        raise _ManualReview("Proposal has no applicable patch.")

    finding = await Finding.get(proposal.finding_id)
    if finding is None or not finding.fingerprint:
        raise _ManualReview("Finding is missing or has no fingerprint; cannot validate the fix.")
    target_fp = finding.fingerprint

    try:
        scan = await Scan.get(proposal.scan_id)
    except Exception:
        scan = None
    repo = await ProjectRepo.get(scan.project_repo_id) if scan and scan.project_repo_id else None
    if scan is None or not scan.repo_url or repo is None:
        raise _ManualReview("No connected repository to open a PR against.")
    if repo.provider not in ("github", "azure_devops"):
        raise _ManualReview(f"Auto-PR is not supported for provider {repo.provider!r}.")

    token, git_scheme, rest_scheme, source = await _resolve_credential(repo, job.approver_user_id)
    base = proposal.base_branch or repo.selected_branch or (scan.branch if scan else None) or "main"

    workdir = tempfile.mkdtemp(prefix="zs-remediate-", dir=git_workspace.workdir_root())
    try:
        git_workspace.validate_repo_url(scan.repo_url)
        await git_workspace.clone_repo(scan.repo_url, base, workdir, token, git_scheme)

        baseline_report, _ = await git_workspace.run_scanner(workdir)
        baseline_fps = _fingerprints(baseline_report)
        if target_fp not in baseline_fps:
            raise _ManualReview("The finding no longer reproduces on a fresh clone; the source may have changed.")

        _apply_patch(workdir, proposal.file_path, proposal.original_code, proposal.patched_code)

        rc, changed_out, _err = await git_workspace.git(["diff", "--name-only"], workdir)
        changed = [line.strip() for line in changed_out.splitlines() if line.strip()]
        if changed != [proposal.file_path]:
            raise _ManualReview(f"The patch modified unexpected files: {changed or 'none'}.")

        post_report, _ = await git_workspace.run_scanner(workdir)
        post_fps = _fingerprints(post_report)
        new_fps = post_fps - baseline_fps
        cfg = await remediation_settings_service.get_settings()
        blocking = {s.lower() for s in cfg.blocking_severities} or _BLOCKING_SEVERITIES
        new_blocking = _new_blocking(post_report, new_fps, blocking)
        target_cleared = target_fp not in post_fps
        proposal.validation = {
            "scope_ok": True,
            "target_cleared": target_cleared,
            "new_finding_count": len(new_fps),
            "new_finding_fingerprints": sorted(new_fps)[:50],
            "baseline_count": len(baseline_fps),
            "post_count": len(post_fps),
            "scanner_version": post_report.scanner_version,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        }
        if not target_cleared:
            raise _ManualReview("The fix did not clear the finding on re-scan.")
        if new_blocking > 0:
            sev_label = "/".join(sorted(blocking))
            raise _ManualReview(
                f"The fix introduced {new_blocking} new {sev_label} finding(s)."
            )
        proposal.review_state = "validated"
        await _save(proposal)
        await audit_service.record(
            "AI Fix Validation Passed", actor_user_id=job.approver_user_id, project_id=proposal.project_id,
            target_type="ai_fix_proposal", target_id=str(proposal.id),
            metadata={"target_cleared": True, "new_finding_count": len(new_fps)},
        )

        branch_name = proposal.branch_name or f"zerostrike/fix-{proposal.finding_id[:8]}-{uuid.uuid4().hex[:8]}"
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
        rc, _ao, aerr = await git_workspace.git(["add", "--", proposal.file_path], workdir)
        if rc != 0:
            raise _ManualReview(f"Could not stage the patch: {aerr[:200]}")
        rule = finding.rule_name or "security finding"
        # Commit/PR use the "zero-strike/security fix: <name>" convention so teammates can spot
        # ZeroStrike-authored security fixes at a glance in git history / the PR list.
        commit_msg = (
            f"zero-strike/security fix: {rule}\n\n"
            f"Fixes {rule} in {proposal.file_path}. ZeroStrike AI Auto-Fix (human-approved). "
            f"{proposal.explanation or ''}"
        ).strip()
        rc, _o, cerr = await git_workspace.git(
            ["-c", "user.name=ZeroStrike Bot", "-c", "user.email=noreply@zerostrike.dev", "commit", "-m", commit_msg],
            workdir,
        )
        if rc != 0:
            raise _ManualReview(f"Could not commit the patch: {cerr[:300]}")
        rc, sha_out, _e = await git_workspace.git(["rev-parse", "HEAD"], workdir)
        commit_sha = sha_out.strip() if rc == 0 else None

        branch_name = await _push_with_recovery(workdir, branch_name, token, git_scheme)
        await audit_service.record(
            "AI Fix Branch Pushed", actor_user_id=job.approver_user_id, project_id=proposal.project_id,
            target_type="ai_fix_proposal", target_id=str(proposal.id),
            metadata={"branch": branch_name, "commit": commit_sha},
        )

        title = f"zero-strike/security fix: {rule}"
        # Same renderer as the downloadable remediation brief (one definition of "how we describe a
        # fix"), minus the diff -- the PR already *is* the diff. proposal.validation is set above,
        # so the re-scan evidence lands in the description a reviewer reads first.
        body = "\n".join(
            [
                "AI-generated fix, reviewed and approved by a human before this PR was opened.",
                "",
                remediation_brief_service.render_proposal_section(
                    proposal, finding, include_diff=False, heading_level=2
                ),
                "",
                "_Review required before merge._",
            ]
        )
        try:
            pr = await _open_pr(repo, token, rest_scheme, branch_name, base, title, body)
        except RepoWriteError as exc:
            raise _ManualReview(str(exc))

        proposal.review_state = "pr_open"
        proposal.status = "applied"
        proposal.branch_name = branch_name
        proposal.commit_sha = commit_sha
        proposal.base_branch = base
        proposal.base_commit_sha = base_sha
        proposal.pr_url = pr["pr_url"]
        proposal.pr_number = pr["pr_number"]
        proposal.pr_provider = repo.provider
        await _save(proposal)
        await audit_service.record(
            "AI Fix PR Opened", actor_user_id=job.approver_user_id, project_id=proposal.project_id,
            target_type="ai_fix_proposal", target_id=str(proposal.id),
            metadata={"pr_url": pr["pr_url"], "pr_number": pr["pr_number"], "branch": branch_name, "base": base, "credential": source},
        )
        # Remember it: this patch cleared the scanner re-scan gate AND a human approved it, so it's
        # the strongest example available for the next occurrence of this rule in this project.
        # Best-effort by contract -- fix_pattern_service swallows its own errors.
        await fix_pattern_service.record(proposal, finding, "pr_open")
    except _ManualReview:
        raise
    except Exception as exc:
        # Scrub the write token from any unexpected error before it propagates to the proposal/job.
        raise RuntimeError(git_workspace.sanitize(str(exc), token)) from exc
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


async def run_job(job: RemediationJob) -> None:
    start = datetime.now(timezone.utc)
    job.status = "running"
    job.started_at = start
    job.updated_at = start
    await job.save()
    structlog.contextvars.bind_contextvars(trace_id=job.trace_id, remediation_job_id=str(job.id))

    proposal = await AIFixProposal.get(job.proposal_id) if job.proposal_id else None
    if proposal is None:
        job.status = "failed"
        job.error_message = "Proposal not found"
        job.completed_at = datetime.now(timezone.utc)
        await job.save()
        structlog.contextvars.clear_contextvars()
        return

    try:
        await _apply(job, proposal)
    except _ManualReview as mr:
        proposal.review_state = "manual_review"
        proposal.manual_review_reason = str(mr)
        await _save(proposal)
        await audit_service.record(
            "AI Fix Marked Manual Review", actor_user_id=job.approver_user_id, project_id=proposal.project_id,
            target_type="ai_fix_proposal", target_id=str(proposal.id), metadata={"reason": str(mr)},
        )
    except Exception as exc:
        logger.exception("remediation apply job failed", job_id=str(job.id))
        proposal.review_state = "failed"
        proposal.failure_reason = git_workspace.sanitize(str(exc), None)[:1000]
        await _save(proposal)
        job.status = "failed"
        job.error_message = str(exc)[:2000]
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        await job.save()
        await audit_service.record(
            "AI Fix Failed", actor_user_id=job.approver_user_id, project_id=proposal.project_id,
            target_type="remediation_job", target_id=str(job.id), metadata={"error": str(exc)[:500]},
        )
        structlog.contextvars.clear_contextvars()
        return

    now = datetime.now(timezone.utc)
    job.status = "completed"
    job.completed_at = now
    job.updated_at = now
    await job.save()
    structlog.contextvars.clear_contextvars()

"""Apply-phase tests for AI Auto-Fix. Mocks the git_workspace + PR boundaries so the validation
gate + branch/commit/push/PR orchestration is exercised without real git or network."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from app.core import security
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.finding import Finding, LocationEmbedded
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.services import ai_remediation_apply_service as apply_svc
from app.services import git_workspace
from app.services.repo_write import github as gh_write

ORIGINAL = "q = 'SELECT * FROM u WHERE id=' + uid"
PATCHED = "q = 'SELECT * FROM u WHERE id=%s'"


def _fp(fp, sev="high"):
    return SimpleNamespace(fingerprint=fp, severity=sev)


def _report(fps):
    return SimpleNamespace(findings=fps, scanner_version="1.2.3")


async def _seed(pat="ghp_token", provider="github", repo_full_name="o/r"):
    now = datetime.now(timezone.utc)
    repo = ProjectRepo(
        project_id="p", provider=provider, organization="o", repo_full_name=repo_full_name,
        clone_url="https://github.com/o/r.git", selected_branch="main",
        pat_encrypted=security.encrypt_secret(pat) if pat else None,
        created_by="u", created_at=now, updated_at=now,
    )
    await repo.insert()
    scan = Scan(
        project_id="p", scan_type="cloud", status="completed", repo_url="https://github.com/o/r.git",
        project_repo_id=str(repo.id), branch="main", created_at=now, updated_at=now,
    )
    await scan.insert()
    finding = Finding(
        scan_id=str(scan.id), project_id="p", fingerprint="fp-target", rule_name="SQL Injection",
        message="m", location=LocationEmbedded(file="app.py", start_line=10), severity="high", created_at=now,
    )
    await finding.insert()
    proposal = AIFixProposal(
        finding_id=str(finding.id), scan_id=str(scan.id), project_id="p", can_fix=True,
        confidence_score=95, original_code=ORIGINAL, patched_code=PATCHED, file_path="app.py",
        explanation="parameterize", review_state="approved",
    )
    await proposal.insert()
    job = RemediationJob(
        kind="apply", project_id="p", scan_id=str(scan.id), proposal_id=str(proposal.id),
        scope_key=f"apply:{proposal.id}", trace_id="t", max_attempts=1, approver_user_id="u",
    )
    await job.insert()
    return proposal, job


def _install_git_mocks(monkeypatch, *, post_findings, diff_files="app.py", push_rc=0, push_err=""):
    """Wire fake clone/scanner/git/PR. clone writes app.py so _apply_patch can read it."""
    def fake_validate(url):
        return None

    async def fake_clone(repo_url, branch, workdir, token=None, auth_scheme="bearer", **kw):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "app.py").write_text(ORIGINAL + "\n", encoding="utf-8")

    scans = {"n": 0}

    async def fake_run_scanner(workdir):
        scans["n"] += 1
        if scans["n"] == 1:
            return _report([_fp("fp-target")]), "{}"  # baseline: target present
        return _report(post_findings), "{}"  # post-patch

    async def fake_git(args, workdir, token=None, auth_scheme="bearer", timeout=120):
        if args[:2] == ["diff", "--name-only"]:
            return 0, "".join(f"{f}\n" for f in diff_files.split(",")), ""
        if args[:1] == ["rev-parse"]:
            return 0, "deadbeef\n", ""
        if args[0] == "push":
            return push_rc, "", push_err
        return 0, "", ""

    async def fake_pr(token, owner, repo, *, head, base, title, body):
        return {"pr_url": f"https://github.com/{owner}/{repo}/pull/1", "pr_number": 1}

    monkeypatch.setattr(git_workspace, "validate_repo_url", fake_validate)
    monkeypatch.setattr(git_workspace, "clone_repo", fake_clone)
    monkeypatch.setattr(git_workspace, "run_scanner", fake_run_scanner)
    monkeypatch.setattr(git_workspace, "git", fake_git)
    monkeypatch.setattr(gh_write, "open_pull_request", fake_pr)


def test_apply_happy_path_opens_pr(client, monkeypatch):
    # post-patch scan: target gone, no new findings.
    _install_git_mocks(monkeypatch, post_findings=[])

    async def run():
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "pr_open"
        assert reloaded.status == "applied"
        assert reloaded.pr_url.endswith("/pull/1")
        assert reloaded.pr_number == 1
        assert reloaded.branch_name and reloaded.branch_name.startswith("zerostrike/fix-")
        assert reloaded.validation["target_cleared"] is True
        job_reloaded = await RemediationJob.get(job.id)
        assert job_reloaded.status == "completed"

    asyncio.run(run())


def test_apply_target_not_cleared_is_manual_review(client, monkeypatch):
    # post-patch scan still reports the target finding.
    _install_git_mocks(monkeypatch, post_findings=[_fp("fp-target")])

    async def run():
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "manual_review"
        assert "did not clear" in reloaded.manual_review_reason
        assert reloaded.pr_url is None

    asyncio.run(run())


def test_apply_new_blocking_finding_is_manual_review(client, monkeypatch):
    # target cleared, but a NEW high-severity finding appears.
    _install_git_mocks(monkeypatch, post_findings=[_fp("fp-new", "high")])

    async def run():
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "manual_review"
        assert "new" in reloaded.manual_review_reason.lower()

    asyncio.run(run())


def test_apply_scope_violation_is_manual_review(client, monkeypatch):
    # git diff reports an extra file beyond the allowlisted one.
    _install_git_mocks(monkeypatch, post_findings=[], diff_files="app.py,other.py")

    async def run():
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "manual_review"
        assert "unexpected files" in reloaded.manual_review_reason

    asyncio.run(run())


def test_apply_push_denied_is_manual_review(client, monkeypatch):
    _install_git_mocks(monkeypatch, post_findings=[], push_rc=1, push_err="remote: Permission to o/r denied (403)")

    async def run():
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "manual_review"
        assert "write permission" in reloaded.manual_review_reason

    asyncio.run(run())


def test_apply_source_changed_is_manual_review(client, monkeypatch):
    # clone writes a file whose content no longer contains original_code.
    _install_git_mocks(monkeypatch, post_findings=[])

    async def fake_clone(repo_url, branch, workdir, token=None, auth_scheme="bearer", **kw):
        Path(workdir).mkdir(parents=True, exist_ok=True)
        (Path(workdir) / "app.py").write_text("totally different content\n", encoding="utf-8")

    monkeypatch.setattr(git_workspace, "clone_repo", fake_clone)

    async def run():
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "manual_review"
        assert "Source changed" in reloaded.manual_review_reason

    asyncio.run(run())

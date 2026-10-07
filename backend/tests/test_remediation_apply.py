"""Apply-phase tests for AI Auto-Fix. Mocks the git_workspace + PR boundaries so the validation
gate + branch/commit/push/PR orchestration is exercised without real git or network."""

import asyncio
from datetime import datetime, timedelta, timezone
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


def test_apply_records_pushed_branch_when_pr_call_fails(client, monkeypatch):
    # The push succeeded, the PR call did not: the branch now exists on the remote with no PR, so its
    # name must be recorded on the job and shown with the failure -- otherwise nobody can find it.
    from app.services.repo_write import RepoWriteError

    _install_git_mocks(monkeypatch, post_findings=[])

    async def failing_pr(token, owner, repo, *, head, base, title, body):
        raise RepoWriteError("GitHub PR creation failed (422): Validation Failed")

    monkeypatch.setattr(gh_write, "open_pull_request", failing_pr)

    async def run():
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        job_reloaded = await RemediationJob.get(job.id)
        assert reloaded.review_state == "manual_review"
        assert job_reloaded.leftover_branch and job_reloaded.leftover_branch.startswith("zerostrike/fix-")
        assert job_reloaded.leftover_branch in reloaded.manual_review_reason
        assert "no PR was opened" in reloaded.manual_review_reason
        assert reloaded.pr_url is None

    asyncio.run(run())


def test_apply_clears_leftover_branch_once_the_pr_exists(client, monkeypatch):
    _install_git_mocks(monkeypatch, post_findings=[])

    async def run():
        _proposal, job = await _seed()
        await apply_svc.run_job(job)
        assert (await RemediationJob.get(job.id)).leftover_branch is None

    asyncio.run(run())


def test_apply_refuses_branch_equal_to_base(client, monkeypatch):
    # An owner-supplied branch name equal to base must never let the commit land on base.
    _install_git_mocks(monkeypatch, post_findings=[])

    async def run():
        proposal, job = await _seed()
        proposal.branch_name = "main"  # base resolves to "main" too
        await proposal.save()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "manual_review"
        assert "base branch" in reloaded.manual_review_reason
        assert reloaded.pr_url is None

    asyncio.run(run())


def test_reconcile_marks_stranded_applying_proposal_failed(client, monkeypatch):
    from app.services import ai_remediation_queue_service as q

    async def run():
        proposal, job = await _seed()
        # Simulate a crash mid-apply: proposal stuck "applying", its apply job no longer active.
        proposal.review_state = "applying"
        await proposal.save()
        # Past the 120 s grace window the reconciler allows for the approve route's two-step write.
        await proposal.set({AIFixProposal.updated_at: datetime.now(timezone.utc) - timedelta(minutes=5)})
        job.status = "failed"
        await job.save()
        await q.reconcile_stranded_proposals()
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "failed"
        assert reloaded.failure_reason

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
        assert "original code was not found" in reloaded.manual_review_reason

    asyncio.run(run())


async def _audit_actions():
    from app.models.audit_log import AuditLog

    return [a.action for a in await AuditLog.find_all().to_list()]


def test_reconcile_leaves_non_lead_batch_proposal_and_fresh_approved_alone(client):
    from app.services import ai_remediation_queue_service as q

    async def run():
        lead, job = await _seed()
        other = AIFixProposal(
            finding_id="f2", scan_id=lead.scan_id, project_id="p", can_fix=True, confidence_score=95,
            file_path="b.py", review_state="applying",
        )
        await other.insert()
        fresh = AIFixProposal(
            finding_id="f3", scan_id=lead.scan_id, project_id="p", can_fix=True, confidence_score=95,
            file_path="c.py", review_state="approved",
        )
        await fresh.insert()
        old = datetime.now(timezone.utc) - timedelta(minutes=5)
        await other.set({AIFixProposal.updated_at: old})
        await job.set({RemediationJob.status: "running", RemediationJob.proposal_ids: [str(lead.id), str(other.id)]})
        await q.reconcile_stranded_proposals()
        # Covered by proposal_ids of a running job, and inside the grace window, respectively.
        assert (await AIFixProposal.get(other.id)).review_state == "applying"
        assert (await AIFixProposal.get(fresh.id)).review_state == "approved"

    asyncio.run(run())


def test_reconcile_fails_a_stranded_validated_proposal(client):
    from app.services import ai_remediation_queue_service as q

    async def run():
        proposal, job = await _seed()
        await proposal.set({AIFixProposal.review_state: "validated",
                            AIFixProposal.updated_at: datetime.now(timezone.utc) - timedelta(minutes=5)})
        await job.set({RemediationJob.status: "failed"})
        await q.reconcile_stranded_proposals()
        assert (await AIFixProposal.get(proposal.id)).review_state == "failed"

    asyncio.run(run())


def _count_scanner_calls(monkeypatch):
    calls = {"n": 0}
    real = git_workspace.run_scanner

    async def counting(workdir):
        calls["n"] += 1
        return await real(workdir)

    monkeypatch.setattr(git_workspace, "run_scanner", counting)
    return calls


def test_apply_with_rescan_disabled_skips_the_scanner_and_opens_pr(client, monkeypatch):
    from app.services import remediation_settings_service

    _install_git_mocks(monkeypatch, post_findings=[])
    calls = _count_scanner_calls(monkeypatch)

    async def run():
        await remediation_settings_service.update_settings(rescan_validation_enabled=False)
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "pr_open"
        assert reloaded.validation["skipped"] is True
        assert reloaded.validation["scope_ok"] is True
        assert calls["n"] == 0
        actions = await _audit_actions()
        assert "AI Fix Validation Skipped" in actions
        assert "AI Fix Validation Passed" not in actions

    asyncio.run(run())


def test_apply_with_rescan_disabled_still_enforces_the_scope_check(client, monkeypatch):
    from app.services import remediation_settings_service

    _install_git_mocks(monkeypatch, post_findings=[], diff_files="app.py,other.py")
    calls = _count_scanner_calls(monkeypatch)

    async def run():
        await remediation_settings_service.update_settings(rescan_validation_enabled=False)
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "manual_review"
        assert "unexpected files" in reloaded.manual_review_reason
        assert calls["n"] == 0

    asyncio.run(run())


def test_apply_records_severities_of_new_findings_below_the_blocking_bar(client, monkeypatch):
    _install_git_mocks(monkeypatch, post_findings=[_fp("n1", "low"), _fp("n2", "LOW"), _fp("n3", None)])

    async def run():
        proposal, job = await _seed()
        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "pr_open"
        assert reloaded.validation["new_finding_count"] == 3
        assert reloaded.validation["new_finding_severities"] == {"low": 2, "unknown": 1}
        assert "high" in reloaded.validation["blocking_severities"]

    asyncio.run(run())


def test_pr_step_refusal_sets_job_error_notifies_and_audits_the_finding(client, monkeypatch):
    from app.services import notification_service
    from app.services.repo_write import RepoWriteError

    _install_git_mocks(monkeypatch, post_findings=[])

    async def failing_pr(token, owner, repo, *, head, base, title, body):
        raise RepoWriteError("GitHub PR creation failed (422): Validation Failed")

    monkeypatch.setattr(gh_write, "open_pull_request", failing_pr)
    sent = []

    async def fake_notify(key, **kw):
        sent.append((key, kw))
        return 0

    monkeypatch.setattr(notification_service, "notify", fake_notify)

    async def run():
        from app.models.audit_log import AuditLog

        proposal, job = await _seed()
        await apply_svc.run_job(job)
        job_reloaded = await RemediationJob.get(job.id)
        assert job_reloaded.status == "completed"
        assert "no PR was opened" in job_reloaded.error_message
        assert [k for k, _ in sent] == ["autofix.apply_failed"]
        assert sent[0][1]["title"] == "Auto-fix pull request was not opened"
        rows = await AuditLog.find(AuditLog.action == "AI Fix Marked Manual Review").to_list()
        assert rows and rows[0].metadata["finding_id"] == proposal.finding_id

    asyncio.run(run())


def test_apply_azure_devops_opens_pr_with_description_within_ado_limit(client, monkeypatch):
    """The ADO path end to end through the real ADO client (HTTP mocked): repo GUID lookup, PR
    create, PAT as Basic auth, PR link built from the response -- and a description that would
    exceed ADO's 4000-char cap is truncated rather than failing the PR after the branch is pushed."""
    import json

    import httpx

    from app.services.repo_write import azure_devops as ado_write

    _install_git_mocks(monkeypatch, post_findings=[])
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"id": "repo-guid"})
        return httpx.Response(201, json={
            "pullRequestId": 7,
            "repository": {"webUrl": "https://dev.azure.com/org/proj/_git/repo"},
        })

    real_client = httpx.AsyncClient
    monkeypatch.setattr(ado_write.httpx, "AsyncClient",
                        lambda **kw: real_client(transport=httpx.MockTransport(handler)))

    async def run():
        proposal, job = await _seed(pat="ado-pat", provider="azure_devops", repo_full_name="proj/repo")
        repo = await ProjectRepo.get((await Scan.get(proposal.scan_id)).project_repo_id)
        repo.organization, repo.ado_project = "org", "proj"
        await repo.save()
        proposal.explanation = "x" * 6000  # renders into the PR body
        await proposal.save()

        await apply_svc.run_job(job)
        reloaded = await AIFixProposal.get(proposal.id)
        assert reloaded.review_state == "pr_open", reloaded.manual_review_reason
        assert reloaded.pr_url == "https://dev.azure.com/org/proj/_git/repo/pullrequest/7"
        assert reloaded.pr_number == 7 and reloaded.pr_provider == "azure_devops"

        lookup, create = calls
        assert lookup.url.path == "/org/proj/_apis/git/repositories/repo"
        assert create.url.path == "/org/proj/_apis/git/repositories/repo-guid/pullrequests"
        assert create.headers["authorization"].startswith("Basic ")
        body = json.loads(create.content)
        assert body["targetRefName"] == "refs/heads/main"
        assert body["sourceRefName"] == f"refs/heads/{reloaded.branch_name}"
        assert len(body["description"]) <= ado_write.MAX_DESCRIPTION
        assert "truncated" in body["description"]

    asyncio.run(run())

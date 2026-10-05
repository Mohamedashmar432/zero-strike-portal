"""Phase D of docs/CLONE_LIFECYCLE_AND_SCAN_REUSE.md: close the auto-fix -> merge -> sync loop.

PR state is read back from the provider on Sync and on demand (provider HTTP is stubbed with an
httpx MockTransport, so the request the code builds is asserted too), merged PRs drive the Repos-tab
reminder and the "Fixed via auto-fix PR #N" attribution, auto-fix spends nothing on findings a later
scan already shows fixed and refuses a superseded scan, and a branch pushed without a PR is recorded.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.audit_log import AuditLog
from app.models.finding import Finding, LocationEmbedded
from app.models.scan import Scan
from app.models.vulnerability import Vulnerability
from app.services import ai_remediation_queue_service, git_workspace, pr_status_service, scan_queue_service
from app.services.repo_write import azure_devops as ado_write
from app.services.repo_write import github as gh_write
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

TOKEN = "ghp_loop_secret_token"
URL = "https://github.com/octocat/repo.git"
SHA = "c" * 40
_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured once: a second _mock_provider must not wrap the first


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture(autouse=True)
def _no_side_effects(monkeypatch):
    monkeypatch.setattr(git_workspace, "validate_repo_url", lambda url: [])

    async def _noop():
        return None

    monkeypatch.setattr(scan_queue_service, "drain_queue", _noop)
    monkeypatch.setattr(ai_remediation_queue_service, "drain_queue", _noop)


def _mock_provider(monkeypatch, handler):
    """Route every httpx.AsyncClient in the repo_write modules through `handler`; returns the requests."""
    seen: list[httpx.Request] = []

    def _handler(request):
        seen.append(request)
        return handler(request)

    def factory(*args, **kwargs):
        return _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(_handler))

    monkeypatch.setattr(gh_write.httpx, "AsyncClient", factory)
    return seen


def _github_pr(state="open", merged=False, merged_at=None, sha=None):
    return {"number": 7, "state": state, "merged": merged, "merged_at": merged_at, "merge_commit_sha": sha}


def _run(coro):
    return asyncio.run(coro)


def _setup(client, email):
    owner = register_and_login(client, email=email)
    headers = _headers(owner)
    project = client.post("/api/v1/projects", json={"name": "Loop"}, headers=headers).json()
    repo = client.post(
        f"/api/v1/projects/{project['id']}/repos",
        json={
            "provider": "github", "pat": TOKEN, "organization": "octocat", "repo_full_name": "octocat/repo",
            "clone_url": URL, "selected_branch": "main",
        },
        headers=headers,
    ).json()
    return headers, project["id"], repo["id"]


async def _scan(pid, rid, *, created_at=None, commit=SHA):
    when = created_at or datetime.now(timezone.utc)
    scan = Scan(
        project_id=pid, scan_type="cloud", status="completed", project_repo_id=rid, repo_url=URL,
        branch="main", git_commit=commit, created_at=when, updated_at=when, completed_at=when,
    )
    await scan.insert()
    return scan


async def _finding(pid, scan_id, fp, vulnerability_id=None):
    f = Finding(
        scan_id=scan_id, project_id=pid, fingerprint=fp, rule_name="SQL Injection", message="m",
        location=LocationEmbedded(file="app.py", start_line=3), severity="high", kind="sast",
        vulnerability_id=vulnerability_id, created_at=datetime.now(timezone.utc),
    )
    await f.insert()
    return f


async def _vuln(pid, rid, fp, *, fixed=True, fixed_commit="f" * 40):
    now = datetime.now(timezone.utc)
    v = Vulnerability(
        project_id=pid, project_repo_id=rid, repo_scope_key=rid, fingerprint=fp,
        status="resolved" if fixed else "open", resolution_reason="fixed" if fixed else None,
        fixed_commit=fixed_commit if fixed else None, first_seen_at=now, last_seen_at=now,
        resolved_at=now if fixed else None,
    )
    await v.insert()
    return v


async def _pr_proposal(pid, scan_id, finding_id, *, number=7, state=None, merged_at=None):
    p = AIFixProposal(
        finding_id=finding_id, scan_id=scan_id, project_id=pid, review_state="pr_open", status="applied",
        can_fix=True, confidence_score=95, pr_number=number,
        pr_url=f"https://github.com/octocat/repo/pull/{number}", pr_provider="github",
        pr_state=state, pr_merged_at=merged_at,
    )
    await p.insert()
    return p


# --- provider adapters --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body,expected",
    [
        (_github_pr("closed", True, "2026-10-05T08:00:00Z", "abc"), ("merged", "2026-10-05T08:00:00Z", "abc")),
        (_github_pr("open"), ("open", None, None)),
        (_github_pr("closed"), ("closed", None, None)),
    ],
)
def test_github_pr_state_mapping_and_token_only_in_header(monkeypatch, body, expected):
    seen = _mock_provider(monkeypatch, lambda req: httpx.Response(200, json=body))
    state = _run(gh_write.get_pull_request_state(TOKEN, "octocat", "repo", 7))
    assert (state["state"], state["merged_at"], state["merge_commit"]) == expected
    (req,) = seen
    assert req.method == "GET" and req.url.path == "/repos/octocat/repo/pulls/7"
    assert TOKEN not in str(req.url)
    assert req.headers["Authorization"] == f"Bearer {TOKEN}"


@pytest.mark.parametrize(
    "status,expected",
    [("completed", "merged"), ("active", "open"), ("abandoned", "closed")],
)
def test_azure_devops_pr_state_mapping(monkeypatch, status, expected):
    body = {"pullRequestId": 12, "status": status, "closedDate": "2026-10-05T08:00:00Z",
            "lastMergeCommit": {"commitId": "def"}}
    seen = _mock_provider(monkeypatch, lambda req: httpx.Response(200, json=body))
    state = _run(ado_write.get_pull_request_state(TOKEN, "basic", "org", "proj", 12))
    assert state["state"] == expected
    assert state["merge_commit"] == ("def" if expected == "merged" else None)
    (req,) = seen
    assert req.url.path == "/org/proj/_apis/git/pullrequests/12"
    assert TOKEN not in str(req.url)
    assert req.headers["Authorization"].startswith("Basic ")


# --- refresh endpoint ---------------------------------------------------------------------------


def test_refresh_stores_merged_state_audits_and_counts_reminder(client, monkeypatch):
    headers, pid, rid = _setup(client, "loop-merged@zerostrike.dev")
    synced = datetime.now(timezone.utc) - timedelta(hours=2)

    async def seed():
        scan = await _scan(pid, rid, created_at=synced)
        f = await _finding(pid, str(scan.id), "fp-1")
        g = await _finding(pid, str(scan.id), "fp-2")
        # Two proposals of one batch PR: one provider call, counted as one PR.
        return [await _pr_proposal(pid, str(scan.id), str(x.id)) for x in (f, g)]

    proposals = _run(seed())
    merged_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    seen = _mock_provider(monkeypatch, lambda req: httpx.Response(200, json=_github_pr("closed", True, merged_at, "m1")))

    r = client.post(f"/api/v1/projects/{pid}/repos/{rid}/pr-status/refresh", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["checked"], body["merged"], body["newly_merged"], body["errors"]) == (1, 1, 1, [])
    assert len(seen) == 1
    assert body["repo"]["autofix_merged_since_sync"] == 1
    assert body["repo"]["autofix_open_prs"] == 0

    for p in proposals:
        reloaded = _run(AIFixProposal.get(p.id))
        assert reloaded.pr_state == "merged" and reloaded.pr_merge_commit == "m1"
        assert reloaded.pr_merged_at is not None and reloaded.pr_check_error is None
    actions = [a.action for a in _run(AuditLog.find(AuditLog.project_id == pid).to_list())]
    assert actions.count("Auto-Fix PR Merged") == 1

    # The list endpoint carries the same reminder count.
    repos = client.get(f"/api/v1/projects/{pid}/repos", headers=headers).json()
    assert repos[0]["autofix_merged_since_sync"] == 1


@pytest.mark.parametrize("status_code,message", [(404, "Not Found"), (401, "Bad credentials")])
def test_refresh_provider_error_is_recorded_not_raised(client, monkeypatch, status_code, message):
    headers, pid, rid = _setup(client, f"loop-err-{status_code}@zerostrike.dev")

    async def seed():
        scan = await _scan(pid, rid)
        f = await _finding(pid, str(scan.id), "fp-1")
        return await _pr_proposal(pid, str(scan.id), str(f.id))

    proposal = _run(seed())
    _mock_provider(monkeypatch, lambda req: httpx.Response(status_code, json={"message": f"{message} {TOKEN}"}))

    r = client.post(f"/api/v1/projects/{pid}/repos/{rid}/pr-status/refresh", headers=headers)
    assert r.status_code == 200
    (err,) = r.json()["errors"]
    assert str(status_code) in err and TOKEN not in err
    reloaded = _run(AIFixProposal.get(proposal.id))
    assert reloaded.pr_state is None  # unknown stays unknown, never guessed
    assert reloaded.pr_check_error and TOKEN not in reloaded.pr_check_error
    assert r.json()["repo"]["autofix_open_prs"] == 1
    logs = _run(AuditLog.find(AuditLog.action == "Auto-Fix PR Status Check Failed").to_list())
    assert len(logs) == 1 and TOKEN not in str(logs[0].metadata)


def test_refresh_is_throttled_and_skips_final_prs(client, monkeypatch):
    headers, pid, rid = _setup(client, "loop-throttle@zerostrike.dev")

    async def seed():
        scan = await _scan(pid, rid)
        f = await _finding(pid, str(scan.id), "fp-1")
        g = await _finding(pid, str(scan.id), "fp-2")
        await _pr_proposal(pid, str(scan.id), str(f.id), number=7)
        await _pr_proposal(pid, str(scan.id), str(g.id), number=8, state="closed")

    _run(seed())
    seen = _mock_provider(monkeypatch, lambda req: httpx.Response(200, json=_github_pr("open")))
    url = f"/api/v1/projects/{pid}/repos/{rid}/pr-status/refresh"
    assert client.post(url, headers=headers).json()["checked"] == 1  # #8 is final: never re-read
    assert client.post(url, headers=headers).json()["checked"] == 0  # #7 read a moment ago
    assert len(seen) == 1


def test_reminder_counts_only_prs_merged_after_last_sync(client):
    headers, pid, rid = _setup(client, "loop-reminder@zerostrike.dev")
    now = datetime.now(timezone.utc)

    async def seed():
        scan = await _scan(pid, rid, created_at=now - timedelta(hours=1))
        fs = [await _finding(pid, str(scan.id), f"fp-{i}") for i in range(4)]
        await _pr_proposal(pid, str(scan.id), str(fs[0].id), number=1, state="merged", merged_at=now - timedelta(hours=3))
        await _pr_proposal(pid, str(scan.id), str(fs[1].id), number=2, state="merged", merged_at=now - timedelta(minutes=1))
        await _pr_proposal(pid, str(scan.id), str(fs[2].id), number=3, state="open")
        await _pr_proposal(pid, str(scan.id), str(fs[3].id), number=4, state="closed")

    _run(seed())
    (repo,) = client.get(f"/api/v1/projects/{pid}/repos", headers=headers).json()
    assert repo["autofix_merged_since_sync"] == 1  # #2 only; #1 merged before the last sync
    assert repo["autofix_open_prs"] == 1


# --- sync integration ---------------------------------------------------------------------------


def test_sync_refreshes_pr_state_and_provider_failure_never_fails_it(client, monkeypatch):
    headers, pid, rid = _setup(client, "loop-sync@zerostrike.dev")

    async def seed():
        scan = await _scan(pid, rid, commit="a" * 40)
        f = await _finding(pid, str(scan.id), "fp-1")
        return await _pr_proposal(pid, str(scan.id), str(f.id))

    proposal = _run(seed())

    async def fake_head(repo_url, branch, token=None, auth_scheme="bearer", timeout=30):
        return "b" * 40

    monkeypatch.setattr(git_workspace, "remote_head", fake_head)

    def boom(req):
        raise httpx.ConnectError("provider down")

    _mock_provider(monkeypatch, boom)
    r = client.post(f"/api/v1/projects/{pid}/repos/{rid}/sync", json={}, headers=headers)
    assert r.status_code == 202 and r.json()["outcome"] == "scan_queued"
    assert _run(AIFixProposal.get(proposal.id)).pr_check_error  # recorded, sync carried on

    # And when the provider answers, Sync is what stores the merge.
    monkeypatch.setattr(pr_status_service, "_RECHECK_AFTER", timedelta(0))  # re-read immediately
    _run(Scan.find(Scan.project_id == pid, Scan.status == "queued").delete())
    _mock_provider(monkeypatch, lambda req: httpx.Response(200, json=_github_pr("closed", True, "2026-10-05T08:00:00Z", "m")))
    assert client.post(f"/api/v1/projects/{pid}/repos/{rid}/sync", json={}, headers=headers).status_code == 202
    assert _run(AIFixProposal.get(proposal.id)).pr_state == "merged"


def test_sync_survives_an_unexpected_pr_refresh_exception(client, monkeypatch):
    headers, pid, rid = _setup(client, "loop-sync-exc@zerostrike.dev")

    async def fake_head(repo_url, branch, token=None, auth_scheme="bearer", timeout=30):
        return "b" * 40

    async def explode(*a, **kw):
        raise RuntimeError("bug")

    monkeypatch.setattr(git_workspace, "remote_head", fake_head)
    monkeypatch.setattr(pr_status_service, "refresh_repo_prs", explode)
    assert client.post(f"/api/v1/projects/{pid}/repos/{rid}/sync", json={}, headers=headers).status_code == 202


# --- attribution --------------------------------------------------------------------------------


@pytest.mark.parametrize("fixed,pr_state,expect", [(True, "merged", True), (True, "open", False), (False, "merged", False)])
def test_fixed_via_pr_only_for_a_merged_pr_on_a_fixed_vulnerability(client, fixed, pr_state, expect):
    headers, pid, rid = _setup(client, f"loop-attr-{fixed}-{pr_state}@zerostrike.dev")

    async def seed():
        scan = await _scan(pid, rid)
        v = await _vuln(pid, rid, "fp-1", fixed=fixed)
        f = await _finding(pid, str(scan.id), "fp-1", vulnerability_id=str(v.id))
        await _pr_proposal(pid, str(scan.id), str(f.id), number=42, state=pr_state,
                           merged_at=datetime.now(timezone.utc) if pr_state == "merged" else None)
        return str(v.id)

    vid = _run(seed())
    body = client.get(f"/api/v1/projects/{pid}/vulnerabilities/{vid}", headers=headers).json()
    if expect:
        assert body["fixed_via_pr"]["pr_number"] == 42
        assert body["fixed_via_pr"]["pr_url"].endswith("/pull/42")
    else:
        assert body["fixed_via_pr"] is None


# --- trigger: skip fixed findings, refuse superseded scans --------------------------------------


def _enable_autofix(client, email):
    admin = _admin_headers(client, email=email)
    r = client.post(
        "/api/v1/ai/providers",
        json={"name": "P", "provider": "anthropic", "model_name": "claude-haiku-4-5", "api_key": "k"},
        headers=admin,
    )
    assert r.status_code == 201


def test_trigger_skips_already_fixed_findings_but_still_lists_them(client):
    _enable_autofix(client, "loop-admin-skip@zerostrike.dev")
    headers, pid, rid = _setup(client, "loop-skip@zerostrike.dev")

    async def seed():
        scan = await _scan(pid, rid)
        v = await _vuln(pid, rid, "fp-fixed", fixed_commit="1234567abcdef" + "0" * 27)
        fixed = await _finding(pid, str(scan.id), "fp-fixed", vulnerability_id=str(v.id))
        live = [await _finding(pid, str(scan.id), f"fp-{i}") for i in range(2)]
        return str(scan.id), str(fixed.id), {str(f.id) for f in live}

    scan_id, fixed_id, live_ids = _run(seed())
    r = client.post(f"/api/v1/scans/{scan_id}/auto-fix", json={}, headers=headers)
    assert r.status_code == 200, r.text
    (job,) = _run(RemediationJob.find(RemediationJob.scan_id == scan_id).to_list())
    assert set(job.finding_ids) == live_ids  # the fixed finding was never selected

    insight = r.json()["insight"]
    assert insight["summary"]["total_findings"] == 3  # the listing is still the whole scan
    assert insight["summary"]["already_fixed_findings"] == 1
    assert insight["summary"]["uncovered_findings"] == 2
    (row,) = insight["already_fixed"]
    assert row["finding_id"] == fixed_id and row["fixed_commit"].startswith("1234567")

    # Explicitly naming the fixed finding (and force) does not get it drafted either.
    _run(RemediationJob.find(RemediationJob.scan_id == scan_id).delete())
    r = client.post(
        f"/api/v1/scans/{scan_id}/auto-fix", json={"finding_ids": [fixed_id], "force": True}, headers=headers
    )
    assert r.status_code == 400 and "already fixed" in r.json()["detail"]


def test_trigger_409s_on_a_superseded_scan(client):
    _enable_autofix(client, "loop-admin-old@zerostrike.dev")
    headers, pid, rid = _setup(client, "loop-old@zerostrike.dev")
    now = datetime.now(timezone.utc)

    async def seed():
        old = await _scan(pid, rid, created_at=now - timedelta(days=1))
        new = await _scan(pid, rid, created_at=now)
        await _finding(pid, str(old.id), "fp-1")
        await _finding(pid, str(new.id), "fp-1")
        return str(old.id), str(new.id)

    old_id, new_id = _run(seed())
    r = client.post(f"/api/v1/scans/{old_id}/auto-fix", json={}, headers=headers)
    assert r.status_code == 409
    assert "newer scan" in r.json()["detail"].lower()
    assert _run(RemediationJob.find(RemediationJob.scan_id == old_id).count()) == 0
    assert client.post(f"/api/v1/scans/{new_id}/auto-fix", json={}, headers=headers).status_code == 200

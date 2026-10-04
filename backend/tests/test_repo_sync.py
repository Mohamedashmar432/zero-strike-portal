"""Repo Sync (docs/REPO_SYNC.md): ls-remote head check, up-to-date short circuit, enqueue, guards.
Subprocesses are stubbed at git_workspace._run and the SSRF DNS check is monkeypatched out."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.services import git_workspace, project_repo_service, scan_queue_service
from app.services.git_workspace import GitWorkspaceError
from tests.test_auth_flow import register_and_login

SHA_A = "a" * 40
SHA_B = "b" * 40
URL = "https://github.com/octocat/repo.git"


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(git_workspace, "validate_repo_url", lambda url: [])

    async def _noop_drain():
        return None

    # The route nudges the queue after enqueueing; a real drain would clone and scan.
    monkeypatch.setattr(scan_queue_service, "drain_queue", _noop_drain)


def _fake_head(monkeypatch, sha=SHA_A, error: str | None = None):
    calls = []

    async def fake(repo_url, branch, token=None, auth_scheme="bearer", timeout=30):
        calls.append((repo_url, branch, token))
        if error:
            raise GitWorkspaceError(error)
        return sha

    monkeypatch.setattr(git_workspace, "remote_head", fake)
    return calls


def _setup(client, email="sync1@zerostrike.dev"):
    owner = register_and_login(client, email=email)
    headers = _headers(owner)
    project = client.post("/api/v1/projects", json={"name": "Demo"}, headers=headers).json()
    repo = client.post(
        f"/api/v1/projects/{project['id']}/repos",
        json={
            "provider": "github",
            "pat": "ghp_sync_token",
            "organization": "octocat",
            "repo_full_name": "octocat/repo",
            "clone_url": URL,
            "selected_branch": "main",
        },
        headers=headers,
    ).json()
    return headers, project["id"], repo["id"]


def _sync(client, headers, pid, rid, **body):
    return client.post(f"/api/v1/projects/{pid}/repos/{rid}/sync", json=body, headers=headers)


def _add_scan(pid, rid, *, status="completed", commit=SHA_A, branch="main"):
    async def go():
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id=pid, scan_type="cloud", triggered_by="cloud", status=status, project_repo_id=rid,
            repo_url=URL, git_commit=commit, branch=branch, created_at=now, updated_at=now,
        )
        await scan.insert()
        return str(scan.id)

    return asyncio.run(go())


def _scans(pid):
    return asyncio.run(Scan.find(Scan.project_id == pid).to_list())


def _repo(rid):
    return asyncio.run(ProjectRepo.get(rid))


# --- git_workspace.remote_head ------------------------------------------------------------


def _stub_run(monkeypatch, rc=0, out=b"", err=b""):
    seen = {}

    async def fake_run(cmd, timeout, env=None, cwd=None):
        seen["cmd"], seen["env"] = cmd, env
        return rc, out, err

    monkeypatch.setattr(git_workspace, "_run", fake_run)
    return seen


def test_remote_head_returns_sha_and_keeps_token_out_of_argv(monkeypatch):
    seen = _stub_run(monkeypatch, out=f"{SHA_A}\trefs/heads/main\n".encode())
    head = asyncio.run(git_workspace.remote_head(URL, "main", "tok-secret", "basic"))
    assert head == SHA_A
    assert seen["cmd"][:3] == ["git", "ls-remote", "--"]
    assert not any("tok-secret" in part for part in seen["cmd"])
    pairs = [seen["env"][f"GIT_CONFIG_VALUE_{i}"] for i in range(int(seen["env"]["GIT_CONFIG_COUNT"]))]
    assert any(v.startswith("AUTHORIZATION: Basic") for v in pairs)


def test_remote_head_ignores_prefix_matching_refs(monkeypatch):
    _stub_run(monkeypatch, out=f"{SHA_B}\trefs/heads/main-old\n".encode())
    with pytest.raises(GitWorkspaceError, match="not found"):
        asyncio.run(git_workspace.remote_head(URL, "main"))


@pytest.mark.parametrize("bad", ["--upload-pack=x", "a b", "a..b", "x;y", ""])
def test_remote_head_rejects_unsafe_branch_names(monkeypatch, bad):
    seen = _stub_run(monkeypatch)
    with pytest.raises(GitWorkspaceError, match="invalid branch"):
        asyncio.run(git_workspace.remote_head(URL, bad))
    assert "cmd" not in seen  # never reached git


def test_remote_head_sanitizes_token_from_errors(monkeypatch):
    _stub_run(monkeypatch, rc=128, err=b"fatal: auth failed for tok-secret")
    with pytest.raises(GitWorkspaceError) as exc:
        asyncio.run(git_workspace.remote_head(URL, "main", "tok-secret"))
    assert "tok-secret" not in str(exc.value)


def test_remote_head_validates_the_url_first(monkeypatch):
    from app.services.cloud_scan_service import CloudScanError

    def reject(url):
        raise CloudScanError("repo_url resolves to a disallowed address")

    monkeypatch.setattr(git_workspace, "validate_repo_url", reject)
    seen = _stub_run(monkeypatch)
    with pytest.raises(GitWorkspaceError, match="disallowed"):
        asyncio.run(git_workspace.remote_head("https://internal.example/x.git", "main"))
    assert "cmd" not in seen


# --- sync endpoint -------------------------------------------------------------------------


def test_sync_enqueues_a_sync_scan_when_there_is_no_prior_scan(client, monkeypatch):
    calls = _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)

    r = _sync(client, headers, pid, rid)

    assert r.status_code == 202
    body = r.json()
    assert body["outcome"] == "scan_queued"
    assert body["remote_head_sha"] == SHA_A
    assert body["repo"]["id"] == rid
    (scan,) = _scans(pid)
    assert str(scan.id) == body["scan_id"]
    assert (scan.triggered_by, scan.scan_type, scan.status) == ("sync", "cloud", "queued")
    assert scan.project_repo_id == rid and scan.branch == "main" and scan.repo_url == URL
    assert scan.repo_token == "ghp_sync_token" and scan.repo_token_auth_scheme == "basic"
    assert calls == [(URL, "main", "ghp_sync_token")]
    repo = _repo(rid)
    assert repo.remote_head_sha == SHA_A and repo.last_sync_error is None
    assert repo.sync_lease_until is None  # released
    actions = {a.action for a in asyncio.run(AuditLog.find(AuditLog.project_id == pid).to_list())}
    assert "Repo Sync Requested" in actions


def test_sync_is_up_to_date_when_latest_scan_covers_the_head(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)
    _add_scan(pid, rid)

    r = _sync(client, headers, pid, rid)

    assert r.status_code == 200
    assert r.json()["outcome"] == "up_to_date" and r.json()["scan_id"] is None
    assert len(_scans(pid)) == 1  # nothing enqueued


def test_force_bypasses_the_up_to_date_short_circuit(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)
    _add_scan(pid, rid)

    r = _sync(client, headers, pid, rid, force=True)

    assert r.status_code == 202 and r.json()["outcome"] == "scan_queued"
    assert len(_scans(pid)) == 2


def test_moved_head_enqueues(client, monkeypatch):
    _fake_head(monkeypatch, sha=SHA_B)
    headers, pid, rid = _setup(client)
    _add_scan(pid, rid, commit=SHA_A)

    assert _sync(client, headers, pid, rid).json()["outcome"] == "scan_queued"


def test_last_scan_without_a_commit_is_never_up_to_date(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)
    _add_scan(pid, rid, commit=None)

    assert _sync(client, headers, pid, rid).json()["outcome"] == "scan_queued"


def test_same_commit_on_another_branch_is_not_up_to_date(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)
    _add_scan(pid, rid, branch="develop")

    assert _sync(client, headers, pid, rid).json()["outcome"] == "scan_queued"


def test_failed_last_scan_is_not_a_baseline(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)
    _add_scan(pid, rid, status="failed")

    assert _sync(client, headers, pid, rid).json()["outcome"] == "scan_queued"


@pytest.mark.parametrize("active", ["queued", "running"])
def test_active_scan_short_circuits_to_already_syncing(client, monkeypatch, active):
    calls = _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)
    scan_id = _add_scan(pid, rid, status=active)

    r = _sync(client, headers, pid, rid)

    assert r.status_code == 200
    assert r.json()["outcome"] == "already_syncing" and r.json()["scan_id"] == scan_id
    assert calls == [] and len(_scans(pid)) == 1


def test_held_lease_returns_409(client, monkeypatch):
    calls = _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)

    async def hold():
        repo = await ProjectRepo.get(rid)
        repo.sync_lease_until = datetime.now(timezone.utc) + timedelta(seconds=60)
        await repo.save()

    asyncio.run(hold())
    r = _sync(client, headers, pid, rid)

    assert r.status_code == 409 and "already in progress" in r.json()["detail"]
    assert calls == [] and _scans(pid) == []


def test_expired_lease_does_not_block(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)

    async def hold():
        repo = await ProjectRepo.get(rid)
        repo.sync_lease_until = datetime.now(timezone.utc) - timedelta(seconds=5)
        await repo.save()

    asyncio.run(hold())
    assert _sync(client, headers, pid, rid).status_code == 202


def test_ls_remote_failure_is_a_readable_409_with_no_scan(client, monkeypatch):
    _fake_head(monkeypatch, error="git ls-remote failed (exit 128): fatal: repository not found")
    headers, pid, rid = _setup(client)

    r = _sync(client, headers, pid, rid)

    assert r.status_code == 409 and "repository not found" in r.json()["detail"]
    assert _scans(pid) == []
    repo = _repo(rid)
    assert "repository not found" in repo.last_sync_error
    assert repo.remote_head_checked_at is not None and repo.sync_lease_until is None
    actions = {a.action for a in asyncio.run(AuditLog.find(AuditLog.project_id == pid).to_list())}
    assert "Repo Sync Failed" in actions


def test_successful_sync_clears_a_previous_error(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)

    async def poison():
        repo = await ProjectRepo.get(rid)
        repo.last_sync_error = "old failure"
        await repo.save()

    asyncio.run(poison())
    _sync(client, headers, pid, rid)
    assert _repo(rid).last_sync_error is None


def test_archived_project_rejects_sync(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)
    client.patch(f"/api/v1/projects/{pid}", json={"is_archived": True}, headers=headers)

    r = _sync(client, headers, pid, rid)

    assert r.status_code == 409 and "archived" in r.json()["detail"].lower()


def test_non_member_cannot_sync(client, monkeypatch):
    _fake_head(monkeypatch)
    _headers_owner, pid, rid = _setup(client)
    outsider = _headers(register_and_login(client, email="outsider-sync@zerostrike.dev"))

    assert _sync(client, outsider, pid, rid).status_code in (403, 404)
    assert _scans(pid) == []


def test_unknown_repo_is_404(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, _rid = _setup(client)

    assert _sync(client, headers, pid, "64b7f0f0f0f0f0f0f0f0f0f0").status_code == 404


def test_sync_is_rate_limited(client, monkeypatch):
    _fake_head(monkeypatch)
    monkeypatch.setattr(settings, "rate_limit_repo_sync_max_attempts", 2)
    headers, pid, rid = _setup(client)
    _add_scan(pid, rid)

    assert [_sync(client, headers, pid, rid).status_code for _ in range(3)] == [200, 200, 429]


def test_branch_change_clears_remembered_head_and_error(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client)
    _sync(client, headers, pid, rid)
    assert _repo(rid).remote_head_sha == SHA_A

    asyncio.run(project_repo_service.update_branch(pid, rid, "develop"))

    repo = _repo(rid)
    assert repo.selected_branch == "develop"
    assert repo.remote_head_sha is None and repo.remote_head_checked_at is None
    assert repo.last_sync_error is None


def test_create_scan_still_enqueues_a_cloud_scan(client, monkeypatch):
    headers, pid, rid = _setup(client)

    r = client.post(
        f"/api/v1/projects/{pid}/scans", json={"scan_type": "cloud", "project_repo_id": rid}, headers=headers
    )

    assert r.status_code == 201 and r.json()["triggered_by"] == "cloud"
    (scan,) = _scans(pid)
    assert scan.status == "queued"
    project = asyncio.run(Project.get(pid))
    assert project.scan_count == 1



# --- phase 3: repo sync_state on the repos list ----------------------------------------------


def _repos(client, headers, pid):
    r = client.get(f"/api/v1/projects/{pid}/repos", headers=headers)
    assert r.status_code == 200
    return {x["id"]: x for x in r.json()}


def _set_repo(rid, **fields):
    async def go():
        repo = await ProjectRepo.get(rid)
        for k, v in fields.items():
            setattr(repo, k, v)
        await repo.save()

    asyncio.run(go())


def test_repo_with_no_completed_scan_is_never(client):
    headers, pid, rid = _setup(client, "state-never@zerostrike.dev")
    row = _repos(client, headers, pid)[rid]
    assert row["sync_state"] == "never" and row["scanned_commit"] is None


def test_scanned_repo_with_unchecked_remote_is_unknown(client):
    headers, pid, rid = _setup(client, "state-unknown@zerostrike.dev")
    _add_scan(pid, rid)
    row = _repos(client, headers, pid)[rid]
    assert row["sync_state"] == "unknown"
    assert (row["scanned_commit"], row["scanned_branch"]) == (SHA_A, "main")


def test_repo_state_up_to_date_vs_behind(client):
    headers, pid, rid = _setup(client, "state-behind@zerostrike.dev")
    _add_scan(pid, rid, commit=SHA_A)
    _set_repo(rid, remote_head_sha=SHA_A, remote_head_checked_at=datetime.now(timezone.utc))
    row = _repos(client, headers, pid)[rid]
    assert row["sync_state"] == "up_to_date" and row["remote_head_sha"] == SHA_A
    assert row["last_synced_at"] is not None

    _set_repo(rid, remote_head_sha=SHA_B)
    assert _repos(client, headers, pid)[rid]["sync_state"] == "behind"


def test_repo_state_error_and_syncing_take_precedence(client):
    headers, pid, rid = _setup(client, "state-prec@zerostrike.dev")
    _add_scan(pid, rid)
    _set_repo(rid, remote_head_sha=SHA_A, last_sync_error="repository not found")
    row = _repos(client, headers, pid)[rid]
    assert row["sync_state"] == "error" and row["last_sync_error"] == "repository not found"

    scan_id = _add_scan(pid, rid, status="running")
    row = _repos(client, headers, pid)[rid]
    assert row["sync_state"] == "syncing" and row["active_scan_id"] == scan_id


def test_repo_state_is_scoped_per_repo(client):
    headers, pid, rid = _setup(client, "state-scope@zerostrike.dev")
    other = client.post(
        f"/api/v1/projects/{pid}/repos",
        json={
            "provider": "github",
            "pat": "ghp_x",
            "organization": "octocat",
            "repo_full_name": "octocat/other",
            "clone_url": "https://github.com/octocat/other.git",
            "selected_branch": "main",
        },
        headers=headers,
    ).json()
    _add_scan(pid, rid)
    rows = _repos(client, headers, pid)
    assert rows[rid]["scanned_commit"] == SHA_A
    assert rows[other["id"]]["sync_state"] == "never"


def test_sync_response_repo_carries_state(client, monkeypatch):
    _fake_head(monkeypatch)
    headers, pid, rid = _setup(client, "state-resp@zerostrike.dev")
    body = _sync(client, headers, pid, rid).json()
    assert body["repo"]["sync_state"] == "syncing"  # the scan it just queued
    assert body["repo"]["active_scan_id"] == body["scan_id"]


# --- phase 3: sync scans notify with what changed ---------------------------------------------


def test_sync_scan_completion_notification_reports_the_diff(client):
    import json
    from pathlib import Path

    from app.models.notification import Notification
    from app.schemas.report import GoReportIn
    from app.services import report_ingestion_service as ingest_svc

    headers, pid, rid = _setup(client, "state-notify@zerostrike.dev")
    fixture = json.loads((Path(__file__).parent / "fixtures" / "go_report_sample.json").read_text())

    async def run_sync_scan(data):
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id=pid, scan_type="cloud", triggered_by="sync", status="running", project_repo_id=rid,
            repo_url=URL, branch="main", created_at=now, updated_at=now,
        )
        await scan.insert()
        await ingest_svc.ingest(scan, GoReportIn.model_validate(data), raw_json="{}")

    asyncio.run(run_sync_scan({**fixture, "GitCommit": SHA_A, "Branch": "main"}))
    fixed_all = {**fixture, "GitCommit": SHA_B, "Branch": "main", "Findings": []}
    asyncio.run(run_sync_scan(fixed_all))

    rows = asyncio.run(Notification.find(Notification.project_id == pid).sort("created_at").to_list())
    bodies = [n.body for n in rows]
    assert bodies[0].startswith(f"Baseline established at {SHA_A[:7]}")
    assert bodies[1].startswith("4 fixed, 0 new, 0 reopened, 0 still open")

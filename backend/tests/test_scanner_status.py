import asyncio
from datetime import datetime, timedelta, timezone

from app.models.scan import Scan
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _publish(client, headers, version, os_, arch, content=b"fake-binary-bytes"):
    return client.post(
        "/api/v1/admin/downloads/zerostrike",
        data={"version": version, "os": os_, "arch": arch},
        files={"file": (f"zerostrike-{os_}-{arch}", content, "application/octet-stream")},
        headers=headers,
    )


def _seed_scan(project_id: str, status: str, updated_at=None, error_message=None) -> str:
    async def _seed():
        now = updated_at or datetime.now(timezone.utc)
        scan = await Scan(
            project_id=project_id,
            scan_type="cloud",
            triggered_by="cloud",
            status=status,
            started_at=now if status in ("running", "completed", "failed") else None,
            completed_at=now if status in ("completed", "failed") else None,
            error_message=error_message,
            created_at=now,
            updated_at=now,
        ).insert()
        return str(scan.id)

    return asyncio.run(_seed())


def test_requires_admin(client):
    tokens = register_and_login(client, email="notadmin-status@zerostrike.dev")
    r = client.get(
        "/api/v1/admin/scanner-status", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert r.status_code == 403


def test_binary_checklist_reports_published_and_missing(client):
    headers = _admin_headers(client, email="statusadmin1@zerostrike.dev")
    _publish(client, headers, "v0.24.0", "linux", "amd64")

    r = client.get("/api/v1/admin/scanner-status", headers=headers)
    assert r.status_code == 200
    body = r.json()

    by_combo = {(b["os"], b["arch"]): b for b in body["binaries"]}
    assert len(by_combo) == 5
    assert by_combo[("linux", "amd64")]["published"] is True
    assert by_combo[("linux", "amd64")]["version"] == "v0.24.0"
    assert by_combo[("linux", "arm64")]["published"] is False
    assert by_combo[("windows", "amd64")]["published"] is False
    assert isinstance(body["engine_available"], bool)


def test_queue_counts_and_failures_reflect_seeded_scans(client):
    headers = _admin_headers(client, email="statusadmin2@zerostrike.dev")
    project = client.post("/api/v1/projects", json={"name": "P"}, headers=headers).json()

    _seed_scan(project["id"], "queued")
    _seed_scan(project["id"], "running")
    _seed_scan(project["id"], "failed", error_message="git clone failed (exit 128)")

    r = client.get("/api/v1/admin/scanner-status", headers=headers)
    assert r.status_code == 200
    body = r.json()

    assert body["queue"]["queued"] == 1
    assert body["queue"]["running"] == 1
    assert len(body["queue"]["running_scans"]) == 1
    assert body["queue"]["running_scans"][0]["stuck"] is False

    assert len(body["recent_failures"]) == 1
    assert body["recent_failures"][0]["error_message"] == "git clone failed (exit 128)"


def test_stuck_running_scan_is_flagged(client):
    headers = _admin_headers(client, email="statusadmin3@zerostrike.dev")
    project = client.post("/api/v1/projects", json={"name": "P"}, headers=headers).json()

    long_ago = datetime.now(timezone.utc) - timedelta(days=1)
    _seed_scan(project["id"], "running", updated_at=long_ago)

    r = client.get("/api/v1/admin/scanner-status", headers=headers)
    assert r.status_code == 200
    running_scans = r.json()["queue"]["running_scans"]
    assert len(running_scans) == 1
    assert running_scans[0]["stuck"] is True


def test_binary_checklist_names_the_uploader_by_email(client):
    headers = _admin_headers(client, email="statusadmin-uploader@zerostrike.dev")
    _publish(client, headers, "v0.24.0", "linux", "amd64")

    body = client.get("/api/v1/admin/scanner-status", headers=headers).json()
    by_combo = {(b["os"], b["arch"]): b for b in body["binaries"]}
    assert by_combo[("linux", "amd64")]["uploaded_by_email"] == "statusadmin-uploader@zerostrike.dev"
    assert by_combo[("linux", "arm64")]["uploaded_by_email"] is None


def test_status_reports_clone_workdirs_size_and_free_disk(client, monkeypatch, tmp_path):
    from app.core.config import settings

    monkeypatch.setattr(settings, "clone_workdir_path", str(tmp_path))
    monkeypatch.setattr(settings, "clone_min_free_mb", 111)
    monkeypatch.setattr(settings, "clone_max_repo_mb", 222)
    (tmp_path / "zs-clone-a").mkdir()
    (tmp_path / "zs-clone-a" / "f.bin").write_bytes(bytes(2 * 1024 * 1024))
    (tmp_path / "zs-remediate-b").mkdir()
    (tmp_path / "unrelated").mkdir()
    headers = _admin_headers(client, email="statusadmin-clones@zerostrike.dev")

    r = client.get("/api/v1/admin/scanner-status", headers=headers)

    assert r.status_code == 200
    clones = r.json()["clones"]
    assert clones["workdir_count"] == 2  # only zs-clone-* / zs-remediate-*
    assert clones["total_mb"] == 2
    assert clones["free_mb"] > 0
    assert clones["min_free_mb"] == 111 and clones["max_repo_mb"] == 222

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

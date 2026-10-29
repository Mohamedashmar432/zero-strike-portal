import asyncio
from datetime import datetime, timezone

import app.services.scan_queue_service as scan_queue_service
from app.core.config import settings
from app.models.scan import Scan
from app.services import cloud_scan_quota_service
from tests.test_auth_flow import register_and_login
from tests.test_scans import _create_project, _headers, _noop
from tests.test_users import _admin_headers


def _seed(project_id, n, *, scan_type="cloud", created_at=None, quota_exempt=False, status="completed"):
    async def run():
        now = created_at or datetime.now(timezone.utc)
        for _ in range(n):
            await Scan(
                project_id=project_id,
                scan_type=scan_type,
                triggered_by="cloud" if scan_type == "cloud" else "ci",
                status=status,
                repo_url="https://github.com/example/seeded",
                quota_exempt=quota_exempt,
                created_at=now,
                updated_at=now,
            ).insert()

    asyncio.run(run())


def _new_scan(client, headers, project_id):
    return client.post(
        f"/api/v1/projects/{project_id}/scans",
        json={"scan_type": "cloud", "repo_url": "https://github.com/example/repo"},
        headers=headers,
    )


def _setup(client, monkeypatch, limit=30):
    monkeypatch.setattr(scan_queue_service, "drain_queue", _noop)
    monkeypatch.setattr(settings, "cloud_scan_monthly_limit_default", limit)
    owner = _headers(register_and_login(client, email="quota-owner@zerostrike.dev"))
    return owner, _create_project(client, owner)["id"]


def test_scan_past_the_monthly_limit_is_409(client, monkeypatch):
    owner, pid = _setup(client, monkeypatch)
    _seed(pid, 30)
    r = _new_scan(client, owner, pid)
    assert r.status_code == 409
    assert r.json()["detail"] == (
        "Cloud scan limit reached: 30/30 this month. Ask a portal admin to raise this project's limit."
    )


def test_scan_under_the_limit_is_created_and_counted(client, monkeypatch):
    owner, pid = _setup(client, monkeypatch)
    _seed(pid, 29)
    assert _new_scan(client, owner, pid).status_code == 201
    quota = client.get(f"/api/v1/projects/{pid}", headers=owner).json()["cloud_scan_quota"]
    assert (quota["used"], quota["limit"], quota["remaining"], quota["is_default"]) == (30, 30, 0, True)


def test_last_months_scans_do_not_count(client, monkeypatch):
    owner, pid = _setup(client, monkeypatch)
    now = datetime.now(timezone.utc)
    last_month = datetime(now.year - (now.month == 1), (now.month - 2) % 12 + 1, 28, tzinfo=timezone.utc)
    _seed(pid, 30, created_at=last_month)
    assert _new_scan(client, owner, pid).status_code == 201


def test_cicd_scans_do_not_count(client, monkeypatch):
    owner, pid = _setup(client, monkeypatch)
    _seed(pid, 30, scan_type="cicd")
    assert _new_scan(client, owner, pid).status_code == 201


def test_quota_exempt_scans_do_not_count(client, monkeypatch):
    owner, pid = _setup(client, monkeypatch)
    _seed(pid, 30, quota_exempt=True, status="failed")
    assert _new_scan(client, owner, pid).status_code == 201


def test_project_override_raises_and_lowers_the_limit_and_null_resets(client, monkeypatch):
    owner, pid = _setup(client, monkeypatch)
    admin = _admin_headers(client)
    url = f"/api/v1/admin/projects/{pid}/cloud-scan-limit"
    _seed(pid, 5)

    r = client.put(url, json={"monthly_limit": 5}, headers=admin)
    assert r.status_code == 200
    assert (r.json()["limit"], r.json()["is_default"]) == (5, False)
    assert _new_scan(client, owner, pid).status_code == 409

    assert client.put(url, json={"monthly_limit": 6}, headers=admin).status_code == 200
    assert _new_scan(client, owner, pid).status_code == 201

    r = client.put(url, json={"monthly_limit": None}, headers=admin)
    assert (r.json()["limit"], r.json()["is_default"]) == (30, True)

    r = client.put(url, json={"monthly_limit": 0}, headers=admin)
    assert _new_scan(client, owner, pid).status_code == 409  # 0 = cloud scanning paused


def test_limit_out_of_range_is_422_and_unknown_project_404(client, monkeypatch):
    _owner, pid = _setup(client, monkeypatch)
    admin = _admin_headers(client)
    url = f"/api/v1/admin/projects/{pid}/cloud-scan-limit"
    assert client.put(url, json={"monthly_limit": -1}, headers=admin).status_code == 422
    assert client.put(url, json={"monthly_limit": 10001}, headers=admin).status_code == 422
    missing = "/api/v1/admin/projects/not-an-id/cloud-scan-limit"
    assert client.put(missing, json={"monthly_limit": 3}, headers=admin).status_code == 404


def test_non_admin_cannot_set_the_limit(client, monkeypatch):
    owner, pid = _setup(client, monkeypatch)
    r = client.put(f"/api/v1/admin/projects/{pid}/cloud-scan-limit", json={"monthly_limit": 999}, headers=owner)
    assert r.status_code == 403


def test_limit_change_is_audited_as_admin_category(client, monkeypatch):
    _owner, pid = _setup(client, monkeypatch)
    admin = _admin_headers(client)
    client.put(f"/api/v1/admin/projects/{pid}/cloud-scan-limit", json={"monthly_limit": 7}, headers=admin)
    from app.services import audit_service

    assert audit_service.classify("Cloud Scan Limit Changed", pid) == "admin"
    rows = client.get("/api/v1/audit-logs?category=admin", headers=admin).json()
    hit = [r for r in rows["items"] if r["action"] == "Cloud Scan Limit Changed"]
    assert hit and hit[0]["metadata"] == {"old": None, "new": 7}


def test_list_carries_quota_from_one_grouped_query(client, monkeypatch):
    owner, pid = _setup(client, monkeypatch)
    _seed(pid, 3)
    items = client.get("/api/v1/projects", headers=owner).json()["items"]
    assert items[0]["cloud_scan_quota"]["used"] == 3


def test_month_start_and_reset_roll_over_the_year():
    dec = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
    start = cloud_scan_quota_service.month_start(dec)
    assert start == datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert cloud_scan_quota_service._next_month(start) == datetime(2027, 1, 1, tzinfo=timezone.utc)

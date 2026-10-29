"""First-party user activity, the insights `users` block, per-project counts, the project activity
endpoint, and new-CVE detection."""

import asyncio
from datetime import datetime, timedelta, timezone

from app.models.finding import DependencyEmbedded, Finding, LocationEmbedded
from app.models.user import User
from app.models.user_activity_day import UserActivityDay
from app.services import activity_service, project_insights_service
from tests.test_auth_flow import register_and_login
from tests.test_scans import _create_project, _headers
from tests.test_users import _admin_headers

_URL = "/api/v1/admin/project-insights"


def _days():
    async def run():
        return await UserActivityDay.find_all().to_list()

    return asyncio.run(run())


def _user(email):
    async def run():
        return await User.find_one(User.email == email)

    return asyncio.run(run())


def _finding(pid, advisories, *, created_at, severity="high", suppressed=False):
    async def run():
        await Finding(
            scan_id="s-" + pid,
            project_id=pid,
            message="vulnerable dependency",
            location=LocationEmbedded(file="requirements.txt"),
            kind="sca",
            severity=severity,
            dependency=DependencyEmbedded(package="x", advisory_ids=advisories),
            suppressed=suppressed,
            created_at=created_at,
        ).insert()

    asyncio.run(run())


def test_authenticated_request_records_one_activity_day_and_last_seen(client):
    h = _headers(register_and_login(client, email="act-a@zs.dev"))
    for _ in range(3):
        assert client.get("/api/v1/auth/me", headers=h).status_code == 200
    rows = _days()
    assert len(rows) == 1
    assert rows[0].day == activity_service.today()
    assert rows[0].project_ids == []
    assert _user("act-a@zs.dev").last_seen_at is not None


def test_activity_write_is_throttled_to_once_per_key(client):
    h = _headers(register_and_login(client, email="act-throttle@zs.dev"))
    client.get("/api/v1/auth/me", headers=h)
    first_seen = _days()[0].last_seen_at

    async def age_row():
        col = UserActivityDay.get_pymongo_collection()
        await col.update_many({}, {"$set": {"last_seen_at": datetime(2020, 1, 1, tzinfo=timezone.utc)}})

    asyncio.run(age_row())
    client.get("/api/v1/auth/me", headers=h)
    # The seen-set short-circuited the second request, so the stamp we aged was not rewritten.
    assert _days()[0].last_seen_at.year == 2020
    assert first_seen.year != 2020


def test_activity_failure_never_raises(monkeypatch):
    class Boom:
        def get_pymongo_collection(self):
            raise RuntimeError("mongo down")

    monkeypatch.setattr(activity_service, "UserActivityDay", Boom())
    asyncio.run(activity_service.touch("0" * 24))  # must not raise


def test_member_counts_for_the_project_but_admin_bypass_does_not(client):
    owner = _headers(register_and_login(client, email="act-owner@zs.dev"))
    pid = _create_project(client, owner, "Activity P")["id"]
    assert client.get(f"/api/v1/projects/{pid}", headers=owner).status_code == 200
    admin = _admin_headers(client, email="act-admin@zs.dev")
    assert client.get(f"/api/v1/projects/{pid}", headers=admin).status_code == 200

    by_user = {r.user_id: r for r in _days()}
    owner_row = by_user[str(_user("act-owner@zs.dev").id)]
    admin_row = by_user[str(_user("act-admin@zs.dev").id)]
    assert pid in owner_row.project_ids
    assert pid not in admin_row.project_ids  # viewing is not being one of the project's users


def test_insights_users_block_and_per_project_counts(client):
    owner = _headers(register_and_login(client, email="act-ins-owner@zs.dev"))
    pid = _create_project(client, owner, "Insights Users")["id"]
    client.get(f"/api/v1/projects/{pid}", headers=owner)
    register_and_login(client, email="act-never@zs.dev")  # registered, logged in once via helper
    admin = _admin_headers(client, email="act-ins-admin@zs.dev")

    body = client.get(_URL, headers=admin).json()
    users = body["users"]
    assert users["total"] == 3
    assert users["registered_in_window"] == 3 and users["registered_today"] == 3
    assert users["active_today"] == 2 and users["active_in_window"] == 2  # owner + admin; "never" only logged in
    assert users["pending_approval"] == 0 and users["disabled"] == 0
    row = next(p for p in body["projects"] if p["project_id"] == pid)
    assert row["members"] == 1 and row["active_users"] == 1
    assert row["new_cves"] == {"count": 0, "latest": []}

    # Window that ends before today excludes today's activity.
    old = client.get(
        _URL,
        params={
            "since": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            "until": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
        },
        headers=admin,
    ).json()
    assert old["users"]["active_in_window"] == 0
    assert old["projects"][0]["active_users"] == 0


def test_activity_endpoint_gates_and_content(client):
    owner = _headers(register_and_login(client, email="act-ep-owner@zs.dev"))
    pid = _create_project(client, owner, "Activity Endpoint")["id"]
    client.get(f"/api/v1/projects/{pid}", headers=owner)
    url = f"{_URL}/projects/{pid}/activity"
    assert client.get(url, headers=owner).status_code == 403
    admin = _admin_headers(client, email="act-ep-admin@zs.dev")
    assert client.get(f"{_URL}/projects/not-an-id/activity", headers=admin).status_code == 404
    assert client.get(f"{_URL}/projects/{'a' * 24}/activity", headers=admin).status_code == 404
    assert client.get(url, params={"limit": 500}, headers=admin).status_code == 422

    body = client.get(url, headers=admin).json()
    assert body["project_id"] == pid and body["name"] == "Activity Endpoint"
    assert [u["email"] for u in body["active_users"]] == ["act-ep-owner@zs.dev"]
    assert body["active_users"][0]["days_active"] == 1
    created = next(e for e in body["timeline"] if e["action"] == "Project Created")
    assert created["actor_email"] == "act-ep-owner@zs.dev" and created["actor_type"] == "user"
    assert body["timeline"] == sorted(body["timeline"], key=lambda e: e["at"], reverse=True)


def test_new_cves_counts_only_ids_first_seen_inside_the_window(client):
    owner = _headers(register_and_login(client, email="act-cve@zs.dev"))
    pid = _create_project(client, owner, "Cve P")["id"]
    now = datetime.now(timezone.utc)
    _finding(pid, ["CVE-2025-0001"], created_at=now - timedelta(days=40))  # before the window
    _finding(pid, ["CVE-2025-0001", "GHSA-aaaa-bbbb-cccc"], created_at=now - timedelta(days=2), severity="critical")
    _finding(pid, ["CVE-2026-1111"], created_at=now - timedelta(days=1), severity="medium")
    _finding(pid, ["CVE-2026-2222"], created_at=now - timedelta(hours=2), suppressed=True)  # suppressed: ignored
    admin = _admin_headers(client, email="act-cve-admin@zs.dev")

    row = next(p for p in client.get(_URL, headers=admin).json()["projects"] if p["project_id"] == pid)
    # CVE-2025-0001 was already reported 40 days ago, so only the other two are new.
    assert row["new_cves"]["count"] == 2
    assert [c["id"] for c in row["new_cves"]["latest"]] == ["CVE-2026-1111", "GHSA-aaaa-bbbb-cccc"]  # newest first
    assert [c["severity"] for c in row["new_cves"]["latest"]] == ["medium", "critical"]

    wide = client.get(
        _URL, params={"since": (now - timedelta(days=90)).isoformat()}, headers=admin
    ).json()
    assert next(p for p in wide["projects"] if p["project_id"] == pid)["new_cves"]["count"] == 3

    found = asyncio.run(project_insights_service.new_cves([pid], now - timedelta(days=30), now))
    assert {a for a, _, _ in found[pid]} == {"GHSA-aaaa-bbbb-cccc", "CVE-2026-1111"}

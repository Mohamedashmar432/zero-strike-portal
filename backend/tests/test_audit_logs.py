"""The audit-log read surface: categorisation, the day window, and the overview counts.

`classify` is the interesting part — the whole point of the three buckets is that someone
can read the access changes without the routine project traffic burying them, so a
privilege event landing in "project" (or vice versa) is a real regression.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.core import request_context
from app.core.config import settings
from app.models.audit_log import AuditLog
from app.services import audit_service
from tests.test_users import _admin_headers

URL = "/api/v1/audit-logs"


# --- classifier (pure) -------------------------------------------------------


def test_access_events_are_privilege_even_inside_a_project():
    # A role change scoped to a project is an access event first. If it fell into "project"
    # it would be buried among the scan traffic, which defeats having the bucket at all.
    assert audit_service.classify("Member Role Updated", "p1") == "privilege"
    assert audit_service.classify("API Key Revoked", "p1") == "privilege"
    assert audit_service.classify("Repo Credential Added", "p1") == "privilege"
    assert audit_service.classify("User Invited", None) == "privilege"
    assert audit_service.classify("login", None) == "privilege"
    assert audit_service.classify("password_changed", None) == "privilege"


def test_project_scoped_work_is_a_project_event():
    assert audit_service.classify("Scan Created", "p1") == "project"
    assert audit_service.classify("Compliance Audit Started", "p1") == "project"
    assert audit_service.classify("AI Fix Approved", "p1") == "project"
    assert audit_service.classify("Project Policy Updated", "p1") == "project"


def test_portal_wide_work_is_an_admin_event():
    assert audit_service.classify("Workspace Settings Updated", None) == "admin"
    assert audit_service.classify("admin.data.purge", None) == "admin"
    assert audit_service.classify("AI Provider Activated", None) == "admin"


def test_failure_is_orthogonal_to_the_bucket():
    # A failed audit is still a project event; "failed" is a filter across all three.
    assert audit_service.classify("Compliance Audit Failed", "p1") == "project"
    assert audit_service.is_failure("Compliance Audit Failed") is True
    assert audit_service.is_failure("Compliance Audit Completed") is False


# --- endpoint ----------------------------------------------------------------


async def _seed(logs: list[tuple[str, str | None, int]]) -> None:
    """(action, project_id, days_ago) triples, inserted directly — the endpoint is a read
    surface, so driving it through every emitting route would test those routes instead."""
    now = datetime.now(timezone.utc)
    for action, project_id, days_ago in logs:
        await AuditLog(
            actor_type="user",
            action=action,
            project_id=project_id,
            created_at=now - timedelta(days=days_ago, minutes=1),
        ).insert()


def test_overview_counts_and_default_one_day_window(client):
    admin = _admin_headers(client, email="audit-window@zs.dev")
    asyncio.run(
        _seed(
            [
                ("Member Role Updated", "p1", 0),
                ("Scan Created", "p1", 0),
                ("Compliance Audit Failed", "p1", 0),
                ("Workspace Settings Updated", None, 0),
                # Outside the default window — must not be counted or listed.
                ("Scan Created", "p1", 3),
            ]
        )
    )

    body = client.get(URL, headers=admin).json()
    assert body["window_days"] == 1
    counts = body["counts"]
    # The admin login that _admin_headers performs is itself a privilege event, so assert on
    # the seeded categories rather than on exact totals for privilege.
    assert counts["privilege"] >= 1
    assert counts["project"] == 2  # Scan Created + Compliance Audit Failed
    assert counts["admin"] == 1
    assert counts["failed"] == 1
    assert counts["total"] == counts["privilege"] + counts["project"] + counts["admin"]

    # The 3-day-old row is excluded by the window, included when the window widens.
    assert client.get(f"{URL}?days=7", headers=admin).json()["counts"]["project"] == 3


def test_category_filter_narrows_the_listing_but_not_the_counts(client):
    admin = _admin_headers(client, email="audit-filter@zs.dev")
    asyncio.run(
        _seed([("Scan Created", "p9", 0), ("Workspace Settings Updated", None, 0)])
    )

    body = client.get(f"{URL}?category=admin", headers=admin).json()
    assert [i["action"] for i in body["items"]] == ["Workspace Settings Updated"]
    assert all(i["category"] == "admin" for i in body["items"])
    # Counts describe the window, not the filtered slice — otherwise the overview would
    # change every time someone clicked a filter chip.
    assert body["counts"]["project"] >= 1


def test_actor_is_resolved_to_an_email_not_an_objectid(client):
    admin = _admin_headers(client, email="audit-actor@zs.dev")
    # The login that just happened was recorded with a real actor_user_id.
    items = client.get(URL, headers=admin).json()["items"]
    logins = [i for i in items if i["action"] == "login"]
    assert logins, "login should be audited"
    assert logins[0]["actor_email"] == "audit-actor@zs.dev"


def test_audit_log_is_admin_only(client):
    from tests.test_auth_flow import register_and_login

    tokens = register_and_login(client, email="audit-nonadmin@zs.dev")
    r = client.get(URL, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 403


def test_legacy_rows_scope_from_metadata_project_id(client):
    admin = _admin_headers(client, email="audit-legacy@zs.dev")
    project = client.post("/api/v1/projects", json={"name": "Legacy Scope"}, headers=admin).json()

    async def seed():
        # Written before callers passed project_id as a field: only metadata names the project.
        await AuditLog(
            actor_type="user",
            action="Project AI Provider Added",
            metadata={"project_id": project["id"]},
        ).insert()

    asyncio.run(seed())
    items = client.get("/api/v1/audit-logs", headers=admin).json()["items"]
    row = next(i for i in items if i["action"] == "Project AI Provider Added")
    assert row["project_id"] == project["id"]
    assert row["project_name"] == "Legacy Scope"
    assert row["category"] == "project"


def test_request_driven_rows_carry_the_client_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    admin = _admin_headers(client, email="audit-ip@zs.dev")
    client.post(
        "/api/v1/projects",
        json={"name": "IP Demo"},
        headers={**admin, "X-Forwarded-For": "203.0.113.7", "User-Agent": "qa-agent/1.0"},
    )

    async def rows():
        return await AuditLog.find(AuditLog.ip_address == "203.0.113.7").to_list()

    found = asyncio.run(rows())
    assert found
    assert all(r.user_agent == "qa-agent/1.0" for r in found)


class _FakeRequest:
    client = type("C", (), {"host": "10.0.0.1"})()
    headers = {"x-forwarded-for": "203.0.113.7", "user-agent": "qa-agent/1.0"}


def test_rows_written_from_a_spawned_task_do_not_inherit_the_request_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)

    async def record_in_spawned_task():
        await audit_service.record("Background Thing", actor_type="user")
        return request_context.current(), await AuditLog.find_one(AuditLog.action == "Background Thing")

    async def scenario():
        await request_context.bind_request_context(_FakeRequest())
        assert request_context.current() == ("203.0.113.7", "qa-agent/1.0")
        # create_task copies the context, but the owning task differs, so nothing is inherited.
        return await asyncio.create_task(record_in_spawned_task())

    ctx, row = asyncio.run(scenario())
    assert ctx == (None, None)
    assert row.ip_address is None

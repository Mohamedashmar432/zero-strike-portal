"""Notification fan-out, audience gating, and per-user preferences.

The properties that matter: an event reaches only people who are eligible AND subscribed, an
admin-audience event never leaks to a non-admin, and a delivery failure never raises into the
caller — the scan or fix that triggered the notification must complete regardless.
"""

import asyncio

from app.core.notification_events import defaults_for
from app.models.notification import Notification
from app.services import notification_service
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

URL = "/api/v1/notifications"
PREFS_URL = "/api/v1/notifications/preferences"


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Notify Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


# --- preferences -------------------------------------------------------------


def test_preferences_default_to_the_catalog_until_a_user_sets_them(client):
    h = _headers(register_and_login(client, email="nt-defaults@zs.dev"))
    body = client.get(PREFS_URL, headers=h).json()
    # Scoped to what this (non-admin) user can actually receive.
    assert body["in_app"] == defaults_for(is_admin=False, channel="in_app")
    # SMTP is unset in tests, as it is in every environment today.
    assert body["email_delivery_configured"] is False


def test_unsubscribing_from_everything_persists_as_empty_not_as_unset(client):
    h = _headers(register_and_login(client, email="nt-optout@zs.dev"))
    assert client.put(PREFS_URL, json={"in_app": []}, headers=h).json()["in_app"] == []
    # Must stay empty on re-read: collapsing [] back to "never chose" would silently
    # re-subscribe them the next time the catalog defaults change.
    assert client.get(PREFS_URL, headers=h).json()["in_app"] == []


def test_a_non_admin_is_never_offered_admin_audience_events(client):
    h = _headers(register_and_login(client, email="nt-audience-user@zs.dev"))
    body = client.get(PREFS_URL, headers=h).json()
    keys = {e["key"] for e in body["events"]}
    # These are only ever delivered to portal admins, so offering the switch — or defaulting
    # them subscribed to it — would be a control that does nothing.
    assert "autofix.quota_requested" not in keys
    assert "scanner.unhealthy" not in keys
    assert "autofix.quota_requested" not in body["in_app"]
    assert "scanner.unhealthy" not in body["email"]


def test_an_admin_is_offered_the_admin_audience_events(client):
    admin = _admin_headers(client, email="nt-audience-admin@zs.dev")
    body = client.get(PREFS_URL, headers=admin).json()
    keys = {e["key"] for e in body["events"]}
    assert "autofix.quota_requested" in keys
    assert "scanner.unhealthy" in keys


def test_unknown_event_key_is_rejected(client):
    h = _headers(register_and_login(client, email="nt-badkey@zs.dev"))
    r = client.put(PREFS_URL, json={"in_app": ["scan.exploded"]}, headers=h)
    assert r.status_code == 422


# --- delivery ----------------------------------------------------------------


def test_project_event_reaches_a_member_and_shows_as_unread(client):
    admin = _admin_headers(client, email="nt-owner@zs.dev")
    project = _create_project(client, admin)

    async def run():
        return await notification_service.notify(
            "scan.completed", project_id=project["id"], title="Scan completed", body="3 high"
        )

    assert asyncio.run(run()) == 1

    body = client.get(URL, headers=admin).json()
    assert body["unread_count"] == 1
    assert body["items"][0]["title"] == "Scan completed"


def test_a_user_who_unsubscribed_receives_nothing(client):
    admin = _admin_headers(client, email="nt-unsub@zs.dev")
    project = _create_project(client, admin, name="Unsub")
    client.put(PREFS_URL, json={"in_app": []}, headers=admin)

    async def run():
        return await notification_service.notify(
            "scan.completed", project_id=project["id"], title="Scan completed"
        )

    assert asyncio.run(run()) == 0
    assert client.get(URL, headers=admin).json()["unread_count"] == 0


def test_admin_audience_event_never_reaches_a_non_admin(client):
    admin = _admin_headers(client, email="nt-admin-aud@zs.dev")
    project = _create_project(client, admin, name="Admin Audience")
    member = register_and_login(client, email="nt-member@zs.dev")
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "nt-member@zs.dev", "role": "collaborator"},
        headers=admin,
    )

    async def run():
        return await notification_service.notify(
            "autofix.quota_requested", project_id=project["id"], title="Wants 20 more"
        )

    asyncio.run(run())
    # The project member is not a portal admin, so this one is not theirs to see even though
    # it names their project.
    assert client.get(URL, headers=_headers(member)).json()["unread_count"] == 0
    assert client.get(URL, headers=admin).json()["unread_count"] == 1


def test_unknown_event_is_logged_not_raised(client):
    async def run():
        # A typo in an emission site must not kill the background task that was notifying.
        return await notification_service.notify("nope.not.real", title="x")

    assert asyncio.run(run()) == 0


def test_delivery_failure_does_not_raise_into_the_caller(client, monkeypatch):
    admin = _admin_headers(client, email="nt-failure@zs.dev")
    project = _create_project(client, admin, name="Failure")

    async def boom(*args, **kwargs):
        raise RuntimeError("mongo is on fire")

    monkeypatch.setattr(Notification, "insert_many", boom)

    async def run():
        return await notification_service.notify(
            "scan.completed", project_id=project["id"], title="Scan completed"
        )

    assert asyncio.run(run()) == 0  # swallowed, not raised


# --- read side ---------------------------------------------------------------


def test_mark_read_is_scoped_to_the_caller(client):
    admin = _admin_headers(client, email="nt-scope-admin@zs.dev")
    other = register_and_login(client, email="nt-scope-other@zs.dev")
    project = _create_project(client, admin, name="Scoped")

    async def run():
        await notification_service.notify(
            "scan.completed", project_id=project["id"], title="Scan completed"
        )

    asyncio.run(run())
    notification_id = client.get(URL, headers=admin).json()["items"][0]["id"]

    # Someone else's id is a no-op, not a cross-user write.
    r = client.post(
        "/api/v1/notifications/read",
        json={"notification_id": notification_id},
        headers=_headers(other),
    )
    assert r.status_code == 200
    assert client.get(URL, headers=admin).json()["unread_count"] == 1

    client.post("/api/v1/notifications/read", json={"notification_id": notification_id}, headers=admin)
    assert client.get(URL, headers=admin).json()["unread_count"] == 0


def test_timestamps_are_serialized_with_a_utc_offset(client):
    """Motor returns naive datetimes. Without an offset in the JSON, a browser's
    `new Date(...)` reads the string as LOCAL time -- a notification from a minute ago
    renders as hours old, wrong by exactly the viewer's UTC offset."""
    admin = _admin_headers(client, email="nt-tz@zs.dev")
    project = _create_project(client, admin, name="Timezones")

    async def run():
        await notification_service.notify(
            "scan.completed", project_id=project["id"], title="Scan completed"
        )

    asyncio.run(run())
    created_at = client.get(URL, headers=admin).json()["items"][0]["created_at"]
    assert created_at.endswith("Z") or "+00:00" in created_at, created_at


def test_mark_all_read_clears_every_unread(client):
    admin = _admin_headers(client, email="nt-markall@zs.dev")
    project = _create_project(client, admin, name="Mark All")

    async def run():
        for i in range(3):
            await notification_service.notify(
                "scan.completed", project_id=project["id"], title=f"Scan {i}"
            )

    asyncio.run(run())
    assert client.get(URL, headers=admin).json()["unread_count"] == 3

    body = client.post("/api/v1/notifications/read", json={}, headers=admin).json()
    assert body["unread_count"] == 0

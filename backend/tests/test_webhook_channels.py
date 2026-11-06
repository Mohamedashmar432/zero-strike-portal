"""Webhook channels: CRUD (the URL is never returned), routing from notify(), the legacy-webhook
migration, alert dedupe, and the new failure events. No test posts to a real webhook."""

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core import dedupe
from app.core.notification_events import EVENTS
from app.core.security import encrypt_secret
from app.models.audit_log import AuditLog
from app.models.scan import Scan
from app.models.webhook_channel import WebhookChannel
from app.services import (
    alert_service,
    audit_service,
    error_alert_service,
    notification_service,
    pipeline_alert_service,
    webhook_channel_service,
    workspace_settings_service,
)
from tests.test_auth_flow import register_and_login
from tests.test_scans import _create_project, _headers
from tests.test_users import _admin_headers

URL = "/api/v1/admin/webhook-channels"
HOOK = "https://example.webhook.office.com/webhookb2/secret-token-123"


@pytest.fixture()
def posts(monkeypatch):
    """Record every webhook post instead of making it; DNS vetting is stubbed."""
    sent = []

    async def fake_post_webhook(url, title, text, link=None, facts=None, **style):
        sent.append({"url": url, "title": title, "text": text, "facts": facts, **style})
        return 200

    monkeypatch.setattr(alert_service, "post_webhook", fake_post_webhook)
    monkeypatch.setattr(alert_service, "resolve_vetted_ips", lambda host: ["93.184.216.34"])
    return sent


def _channel(client, admin, **overrides):
    body = {"name": "Incidents", "url": HOOK, "events": ["scanner.unhealthy"], **overrides}
    r = client.post(URL, json=body, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()


def _notify(event, **kwargs):
    async def run():
        count = await notification_service.notify(event, **kwargs)
        await webhook_channel_service.drain()
        return count

    return asyncio.run(run())


# --- CRUD -------------------------------------------------------------------------------------


def test_channel_crud_never_returns_the_url(client, posts):
    admin = _admin_headers(client, email="wc-admin@zs.dev")
    created = _channel(client, admin, include_digest=True)
    assert created["url_host"] == "example.webhook.office.com"
    assert created["enabled"] is True and created["include_digest"] is True
    assert created["last_status"] is None and created["last_delivery_at"] is None
    assert "secret-token" not in str(created)

    listing = client.get(URL, headers=admin)
    assert "secret-token" not in listing.text and [c["id"] for c in listing.json()] == [created["id"]]

    # url omitted = unchanged
    r = client.patch(f"{URL}/{created['id']}", json={"name": "Renamed", "enabled": False}, headers=admin)
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["enabled"] is False
    assert r.json()["url_host"] == "example.webhook.office.com"
    r = client.patch(
        f"{URL}/{created['id']}", json={"url": "https://other.example.com/hook/abc"}, headers=admin
    )
    assert r.json()["url_host"] == "other.example.com" and "abc" not in r.text

    assert client.delete(f"{URL}/{created['id']}", headers=admin).status_code == 204
    assert client.delete(f"{URL}/{created['id']}", headers=admin).status_code == 404
    assert client.patch(f"{URL}/{created['id']}", json={}, headers=admin).status_code == 404


def test_validation_unknown_event_and_bad_url_are_422(client, posts):
    admin = _admin_headers(client, email="wc-val@zs.dev")
    bad_event = client.post(URL, json={"name": "x", "url": HOOK, "events": ["nope.nothing"]}, headers=admin)
    assert bad_event.status_code == 422 and "nope.nothing" in bad_event.text
    http_url = client.post(URL, json={"name": "x", "url": "http://example.com/h"}, headers=admin)
    assert http_url.status_code == 422 and "https" in http_url.text
    created = _channel(client, admin)
    assert client.patch(f"{URL}/{created['id']}", json={"events": ["bogus"]}, headers=admin).status_code == 422
    assert client.patch(f"{URL}/{created['id']}", json={"url": "ftp://x"}, headers=admin).status_code == 422


def test_non_admin_is_403_everywhere(client, posts):
    user = _headers(register_and_login(client, email="wc-plain@zs.dev"))
    assert client.get(URL, headers=user).status_code == 403
    assert client.get(f"{URL}/events", headers=user).status_code == 403
    assert client.post(URL, json={"name": "x", "url": HOOK}, headers=user).status_code == 403


def test_events_endpoint_lists_the_whole_catalog(client):
    admin = _admin_headers(client, email="wc-events@zs.dev")
    events = client.get(f"{URL}/events", headers=admin).json()
    assert {e["key"] for e in events} == {e.key for e in EVENTS}
    assert {"scanner.download_failed", "pipeline.upload_stalled", "pipeline.silent", "portal.error"} <= {
        e["key"] for e in events
    }
    assert "digest" not in {e["key"] for e in events}
    assert all(e["group"] and e["audience"] in ("project", "admin") for e in events)


def test_test_endpoint_reports_ok_and_failure_and_records_status(client, posts, monkeypatch):
    admin = _admin_headers(client, email="wc-test@zs.dev")
    created = _channel(client, admin)
    r = client.post(f"{URL}/{created['id']}/test", headers=admin)
    assert r.json() == {"ok": True, "status": 200, "error": None}
    assert len(posts) == 1 and posts[0]["url"] == HOOK

    async def failing(url, title, text, link=None, facts=None, **style):
        raise RuntimeError(f"cannot reach {url}")

    monkeypatch.setattr(alert_service, "post_webhook", failing)
    r = client.post(f"{URL}/{created['id']}/test", headers=admin).json()
    assert r["ok"] is False and r["error"] == "RuntimeError" and "secret-token" not in str(r)
    channel = client.get(URL, headers=admin).json()[0]
    assert channel["last_status"] == "error" and channel["last_error"] == "RuntimeError"
    assert client.post(f"{URL}/{'b' * 24}/test", headers=admin).status_code == 404


def test_admin_actions_are_audited_as_admin_and_never_carry_the_url(client, posts):
    admin = _admin_headers(client, email="wc-audit@zs.dev")
    created = _channel(client, admin)
    client.post(f"{URL}/{created['id']}/test", headers=admin)
    client.delete(f"{URL}/{created['id']}", headers=admin)

    async def rows():
        return await AuditLog.find(AuditLog.target_type == "webhook_channel").to_list()

    found = asyncio.run(rows())
    assert {r.action for r in found} == {"Webhook Channel Created", "Webhook Channel Tested", "Webhook Channel Deleted"}
    assert all(audit_service.classify(r.action, r.project_id) == "admin" for r in found)
    assert "secret-token" not in str([r.metadata for r in found])
    for action in ("Digest Settings Updated", "Digest Test Sent", "Digest Sent", "Digest Send Failed"):
        assert audit_service.classify(action, None) == "admin"


# --- routing ----------------------------------------------------------------------------------


def test_routing_filters_by_event_project_and_enabled(client, posts):
    admin = _admin_headers(client, email="wc-route@zs.dev")
    owner = _headers(register_and_login(client, email="wc-route-owner@zs.dev"))
    p1 = _create_project(client, owner, "Route One")["id"]
    p2 = _create_project(client, owner, "Route Two")["id"]
    _channel(client, admin, name="only-p1", events=["scan.failed"], project_ids=[p1], url=HOOK + "/a")
    _channel(client, admin, name="all-projects", events=["scan.failed"], url=HOOK + "/b")
    _channel(client, admin, name="other-event", events=["scanner.unhealthy"], url=HOOK + "/c")
    _channel(client, admin, name="disabled", events=["scan.failed"], enabled=False, url=HOOK + "/d")

    _notify("scan.failed", project_id=p1, title="p1 failed", body="boom", facts=[("Stage", "cloning")])
    assert sorted(p["url"][-1] for p in posts) == ["a", "b"]
    assert posts[0]["eyebrow"] == "Scan failed" and posts[0]["tone"] == "attention"
    assert ("Stage", "cloning") in posts[0]["facts"]

    posts.clear()
    _notify("scan.failed", project_id=p2, title="p2 failed")
    assert [p["url"][-1] for p in posts] == ["b"]

    posts.clear()
    _notify("scanner.unhealthy", title="engine down")  # admin event, no project
    assert [p["url"][-1] for p in posts] == ["c"]

    channels = {c["name"]: c for c in client.get(URL, headers=admin).json()}
    assert channels["only-p1"]["last_status"] == "ok" and channels["only-p1"]["last_delivery_at"]
    assert channels["disabled"]["last_status"] is None


def test_delivery_failure_is_recorded_logged_as_warning_and_never_raises(client, posts, monkeypatch):
    admin = _admin_headers(client, email="wc-fail@zs.dev")
    _channel(client, admin, events=["scanner.unhealthy"])
    levels = []

    class Recorder:
        def __getattr__(self, level):
            return lambda *a, **k: levels.append(level)

    monkeypatch.setattr(webhook_channel_service, "logger", Recorder())

    async def failing(url, title, text, link=None, facts=None, **style):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(alert_service, "post_webhook", failing)
    _notify("scanner.unhealthy", title="t")  # must not raise
    assert levels == ["warning"]  # never error/exception: that is what portal.error alerts on
    channel = client.get(URL, headers=admin).json()[0]
    assert channel["last_status"] == "error" and channel["last_error"] == "ConnectError"
    assert error_alert_service._eligible({"level": "warning", "logger": "x", "message": "m"}) is False


# --- legacy migration -------------------------------------------------------------------------


def _set_legacy(enabled=True):
    async def run():
        ws = await workspace_settings_service.get_workspace_settings()
        ws.alert_webhook_enc = encrypt_secret(HOOK)
        ws.alert_webhook_enabled = enabled
        await ws.save()

    asyncio.run(run())


def test_migration_creates_one_admin_alerts_channel_and_is_idempotent(client, posts, monkeypatch):
    _set_legacy()

    async def run():
        first = await webhook_channel_service.migrate_legacy_webhook()
        second = await webhook_channel_service.migrate_legacy_webhook()
        return first, second, await WebhookChannel.find_all().to_list()

    first, second, channels = asyncio.run(run())
    assert (first, second) == (True, False) and len(channels) == 1
    channel = channels[0]
    assert channel.name == "Admin alerts" and channel.enabled is True and channel.include_digest is False
    assert set(channel.events) == {e.key for e in EVENTS if e.audience == "admin"}
    assert channel.migrated_from_workspace is True

    # An admin event now posts exactly once: the channel routes it, send_global stands down.
    legacy = []

    async def spy(*args, **kwargs):
        legacy.append(args)

    monkeypatch.setattr(alert_service, "_safe_webhook", spy)
    _notify("scanner.unhealthy", title="engine down")
    assert len(posts) == 1 and legacy == []


def test_without_a_migrated_channel_send_global_still_posts(client, posts, monkeypatch):
    _set_legacy()
    legacy = []

    async def spy(*args, **kwargs):
        legacy.append(args)

    monkeypatch.setattr(alert_service, "_safe_webhook", spy)

    async def run():
        await notification_service.notify("scanner.unhealthy", title="engine down")
        await asyncio.sleep(0)

    asyncio.run(run())
    assert len(legacy) == 1


def test_legacy_settings_page_edits_flow_into_the_migrated_channel(client, posts):
    admin = _admin_headers(client, email="wc-legacy@zs.dev")
    r = client.put(
        "/api/v1/workspace-settings/alerts", json={"webhook_url": HOOK, "webhook_enabled": True}, headers=admin
    )
    assert r.status_code == 200
    channels = client.get(URL, headers=admin).json()
    assert [c["name"] for c in channels] == ["Admin alerts"] and channels[0]["enabled"] is True
    client.put("/api/v1/workspace-settings/alerts", json={"webhook_enabled": False}, headers=admin)
    assert client.get(URL, headers=admin).json()[0]["enabled"] is False


# --- dedupe -----------------------------------------------------------------------------------


def test_dedupe_window_and_group_cap(monkeypatch):
    gate = dedupe.TTLDedupe()
    clock = [1000.0]
    monkeypatch.setattr(dedupe.time, "monotonic", lambda: clock[0])
    assert gate.first("k", 3600) is True
    assert gate.first("k", 3600) is False
    clock[0] += 3601
    assert gate.first("k", 3600) is True  # window elapsed

    capped = [gate.first(f"v{i}", 3600, group="g", group_cap=3) for i in range(5)]
    assert capped == [True, True, True, False, False]


def test_portal_error_groups_by_logger_and_normalised_message_once_per_hour(monkeypatch):
    calls = []

    async def fake_notify(event, **kwargs):
        calls.append((event, kwargs["title"]))
        return 0

    monkeypatch.setattr(notification_service, "notify", fake_notify)
    rows = [
        {"level": "error", "logger": "app.x", "message": "scan 123 blew up"},
        {"level": "error", "logger": "app.x", "message": "scan 4567 blew up"},  # same fingerprint
        {"level": "error", "logger": "app.y", "message": "scan 123 blew up"},  # different logger
        {"level": "warning", "logger": "app.x", "message": "just a warning"},
        {"level": "error", "logger": "app.services.webhook_channel_service", "message": "self"},  # never alerts
    ]
    assert asyncio.run(error_alert_service.alert_rows(rows)) == 2
    assert [c[0] for c in calls] == ["portal.error", "portal.error"]
    assert asyncio.run(error_alert_service.alert_rows(rows)) == 0  # still inside the hour


# --- new events -------------------------------------------------------------------------------


def _recorder(monkeypatch):
    calls = []

    async def fake_notify(event, **kwargs):
        calls.append((event, kwargs))
        return 0

    monkeypatch.setattr(notification_service, "notify", fake_notify)
    return calls


def test_download_failures_alert_once_per_reason_and_are_capped(client, monkeypatch):
    calls = _recorder(monkeypatch)
    base = "/api/v1/downloads/zerostrike"
    assert client.get(f"{base}/9.9.9/linux-amd64").status_code == 404
    assert client.get(f"{base}/9.9.9/linux-amd64").status_code == 404  # deduped
    assert client.get(f"{base}/9.9.9/checksums.txt").status_code == 404
    assert client.get(f"{base}/9.9.9/not-a-platform").status_code == 400  # scanner noise: never alerted
    assert [c[0] for c in calls] == ["scanner.download_failed", "scanner.download_failed"]
    reasons = [dict(c[1]["facts"])["Reason"] for c in calls]
    assert reasons == ["no_binary", "checksum_missing"]

    calls.clear()
    for i in range(15):  # a public endpoint cannot mint unlimited alerts by inventing versions
        client.get(f"{base}/v{i}.0.0/linux-amd64")
    assert len(calls) <= 10


def _insert_scan(project_id, *, scan_type="cicd", status="pending", age=timedelta(hours=3), **extra):
    async def run():
        at = datetime.now(timezone.utc) - age
        scan = Scan(
            project_id=project_id, scan_type=scan_type, status=status, created_at=at, updated_at=at, **extra
        )
        await scan.insert()
        return scan

    return asyncio.run(run())


def test_stalled_cicd_scan_alerts_exactly_once(client, monkeypatch):
    owner = _headers(register_and_login(client, email="wc-stall@zs.dev"))
    pid = _create_project(client, owner, "Stall P")["id"]
    calls = _recorder(monkeypatch)
    stalled = _insert_scan(pid, status="running", age=timedelta(hours=3), branch="main", ci_build_url="https://ci/1")
    _insert_scan(pid, status="pending", age=timedelta(minutes=5))  # fresh: not stalled
    _insert_scan(pid, status="completed", age=timedelta(hours=3))  # finished: not stalled
    _insert_scan(pid, scan_type="cloud", status="running", age=timedelta(hours=3))  # reaper's job, not ours

    assert asyncio.run(pipeline_alert_service.check_stalled()) == 1
    assert asyncio.run(pipeline_alert_service.check_stalled()) == 0
    [(event, kw)] = calls
    assert event == "pipeline.upload_stalled" and kw["project_id"] == pid
    assert kw["link"].endswith(str(stalled.id))
    assert ("CI build", "https://ci/1") in kw["facts"] and ("Branch", "main") in kw["facts"]


def test_silent_pipeline_needs_three_active_days_and_24h_of_quiet_and_alerts_once_a_day(client, monkeypatch):
    owner = _headers(register_and_login(client, email="wc-silent@zs.dev"))
    quiet = _create_project(client, owner, "Quiet P")["id"]
    chatty = _create_project(client, owner, "Chatty P")["id"]
    sparse = _create_project(client, owner, "Sparse P")["id"]
    for days in (2, 3, 4):
        _insert_scan(quiet, status="completed", age=timedelta(days=days))
    for days in (0, 2, 3):
        _insert_scan(chatty, status="completed", age=timedelta(days=days, minutes=1))
    _insert_scan(sparse, status="completed", age=timedelta(days=2))
    calls = _recorder(monkeypatch)

    assert asyncio.run(pipeline_alert_service.check_silent()) == 1
    assert asyncio.run(pipeline_alert_service.check_silent()) == 0  # same day
    assert [(c[0], c[1]["project_id"]) for c in calls] == [("pipeline.silent", quiet)]


def test_scan_failed_card_carries_context_and_fires_once_per_scan(client, monkeypatch):
    owner = _headers(register_and_login(client, email="wc-failed@zs.dev"))
    pid = _create_project(client, owner, "Failed P")["id"]
    calls = _recorder(monkeypatch)
    scan = _insert_scan(
        pid,
        scan_type="cloud",
        status="failed",
        age=timedelta(minutes=1),
        stage="cloning",
        error_message="clone failed: repository not found",
        repo_url="https://github.com/example/repo",
        branch="dev",
    )
    asyncio.run(pipeline_alert_service.notify_scan_failed(scan))
    asyncio.run(pipeline_alert_service.notify_scan_failed(scan))
    [(event, kw)] = calls
    assert event == "scan.failed" and kw["body"] == "clone failed: repository not found"
    facts = dict(kw["facts"])
    assert facts["Scan type"] == "Cloud" and facts["Stage"] == "cloning" and facts["Branch"] == "dev"
    assert facts["Project"] == "Failed P" and facts["Repository"] == "https://github.com/example/repo"


def test_cicd_status_failed_through_the_api_fires_scan_failed_once(client, monkeypatch):
    owner = _headers(register_and_login(client, email="wc-cicd@zs.dev"))
    pid = _create_project(client, owner, "Cicd Failed")["id"]
    calls = _recorder(monkeypatch)
    raw_token = client.post(
        "/api/v1/apikeys",
        json={"project_id": pid, "label": "scanner", "expires_in_days": 30},
        headers=owner,
    ).json()["raw_token"]
    key_headers = {"Authorization": f"Bearer {raw_token}"}
    scan_id = client.post(
        "/api/v1/scans", json={"project_id": pid, "scanner_version": "v0.22.0"}, headers=key_headers
    ).json()["scan_id"]
    for _ in range(2):
        r = client.put(
            f"/api/v1/scans/{scan_id}/status",
            json={"status": "failed", "error_message": "tests red"},
            headers=key_headers,
        )
        assert r.status_code == 200
    assert [c[0] for c in calls] == ["scan.failed"]


# --- developer alerts: failures that must still reach portal.error ----------------------------


def test_portal_error_falls_back_to_the_last_loaded_channels_when_mongo_is_down(client, posts, monkeypatch):
    admin = _admin_headers(client, email="wc-dbdown@zs.dev")
    _channel(client, admin, events=["portal.error", "scanner.unhealthy"])
    _notify("portal.error", title="first")  # a healthy lookup fills the cache
    assert len(posts) == 1
    posts.clear()

    async def down(*args, **kwargs):
        raise RuntimeError("mongo is down")

    class _Down:
        def __getattr__(self, name):
            return down

    monkeypatch.setattr(WebhookChannel, "find", lambda *a, **k: _Down())
    _notify("portal.error", title="database unreachable")
    assert [p["title"] for p in posts] == ["database unreachable"] and posts[0]["url"] == HOOK
    # Only portal.error gets the fallback: any other event stays silent rather than guessing at routing.
    posts.clear()
    _notify("scanner.unhealthy", title="engine down")
    assert posts == []


def test_a_fresh_process_with_mongo_down_has_no_cache_and_does_not_raise(client, posts, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("mongo is down")

    monkeypatch.setattr(WebhookChannel, "find", boom)
    assert _notify("portal.error", title="nowhere to send") == 0 and posts == []


def test_the_poll_loop_ping_logs_error_when_the_database_is_unreachable(monkeypatch):
    import structlog

    from app.services import scan_queue_service

    assert asyncio.run(scan_queue_service.check_database()) is True

    class _Dead:
        async def command(self, *args):
            raise ConnectionError("mongodb://user:pw@host/db unreachable")

    monkeypatch.setattr(scan_queue_service, "get_database", lambda: _Dead())
    with structlog.testing.capture_logs() as logs:
        assert asyncio.run(scan_queue_service.check_database()) is False
    (entry,) = logs
    assert entry["log_level"] == "error" and entry["event"] == "database unreachable"
    assert "pw" not in str(entry)  # the exception type only, never its text


def test_an_unhandled_exception_is_logged_at_error_and_answered_with_json_and_a_request_id(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main_module

    calls = []

    class Recorder:
        def __getattr__(self, level):
            return lambda event, **kw: calls.append((level, event, kw))

    monkeypatch.setattr(main_module, "logger", Recorder())
    app = main_module.create_app()

    @app.get("/boom-for-test")
    async def boom():
        raise RuntimeError("synthetic failure")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/boom-for-test", headers={"X-Request-ID": "req-123"})
    assert r.status_code == 500 and r.headers["X-Request-ID"] == "req-123"
    assert r.json() == {"detail": "Internal server error", "request_id": "req-123"}
    (level, event, kw), = [c for c in calls if c[1] == "unhandled exception"]
    assert level == "error" and kw["path"] == "/boom-for-test" and "synthetic failure" not in r.text


def test_uvicorns_copy_of_an_unhandled_crash_does_not_alert_a_second_time():
    ours = {"level": "error", "logger": "app.main", "message": "unhandled exception"}
    theirs = {"level": "error", "logger": "uvicorn.error", "message": "Exception in ASGI application"}
    other = {"level": "error", "logger": "uvicorn.error", "message": "Failed to bind"}
    assert [error_alert_service._eligible(r) for r in (ours, theirs, other)] == [True, False, True]

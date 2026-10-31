"""The live-alert HTTP surface: admin status/settings/run, the per-project policy and feed, and the
notification catalog. The engine itself is covered in test_live_alerts.py."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet

from app.core.config import Settings
from app.models.audit_log import AuditLog
from app.services import live_alert_service
from tests.test_auth_flow import register_and_login
from tests.test_live_alerts import T0, T1, FakeFeed, _inventory, tick
from tests.test_scans import _create_project, _headers
from tests.test_users import _admin_headers

BASE = "/api/v1/admin/live-alerts"
PREFS = "/api/v1/notifications/preferences"


def _member_of(client, tag):
    """(owner headers, member headers, project id): the member was invited into the owner's project."""
    owner = _headers(register_and_login(client, email=f"api-owner-{tag}@zs.dev"))
    member = _headers(register_and_login(client, email=f"api-member-{tag}@zs.dev"))
    pid = _create_project(client, owner, name=f"Api {tag}")["id"]
    r = client.post(f"/api/v1/projects/{pid}/members", json={"email": f"api-member-{tag}@zs.dev"}, headers=owner)
    assert r.status_code == 201
    return owner, member, pid


def test_members_are_refused_on_the_admin_routes(client):
    member = _headers(register_and_login(client, email="api-plain@zs.dev"))
    assert client.get(BASE, headers=member).status_code == 403
    assert client.put(BASE, json={"enabled": False}, headers=member).status_code == 403
    assert client.post(f"{BASE}/run", headers=member).status_code == 403
    assert client.get(BASE).status_code in (401, 403)


def test_status_defaults_and_settings_update_is_audited(client):
    admin = _admin_headers(client, email="api-admin1@zs.dev")
    body = client.get(BASE, headers=admin).json()
    assert body["enabled"] is True and body["min_severity"] == "high" and body["include_malicious"] is True
    assert body["server_watch_enabled"] is True and body["interval_minutes"] == 60 and body["max_age_hours"] == 72
    assert [e["ecosystem"] for e in body["ecosystems"]] == ["npm", "PyPI", "Go", "Maven", "NuGet"]
    assert all(e["cursor"] is None and e["lag_minutes"] is None for e in body["ecosystems"])
    assert body["last_status"] is None and body["recent"] == [] and body["email_delivery_configured"] is False
    assert set(body["coverage"]) == {
        "projects_active", "projects_with_inventory", "inventories_cloud", "inventories_cicd", "oldest_inventory_at"
    }

    r = client.put(BASE, json={"min_severity": "critical", "include_malicious": False}, headers=admin)
    assert r.status_code == 200 and r.json()["min_severity"] == "critical" and r.json()["include_malicious"] is False
    assert client.put(BASE, json={"min_severity": "low"}, headers=admin).status_code == 422
    rows = asyncio.run(AuditLog.find(AuditLog.action == "Live Alert Settings Changed").to_list())
    assert rows and rows[0].metadata["live_alerts_min_severity"] == "critical"


def test_run_dry_run_and_the_409_while_busy(client, monkeypatch):
    admin = _admin_headers(client, email="api-admin2@zs.dev")
    FakeFeed(monkeypatch)
    r = client.post(f"{BASE}/run", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "ran" and r.json()["dry_run"] is False
    assert r.json()["previews"] == []
    state = client.get(BASE, headers=admin).json()
    assert state["last_status"] == "ok" and all(e["cursor"] for e in state["ecosystems"])

    dry = client.post(f"{BASE}/run?dry_run=true", headers=admin)
    assert dry.status_code == 200 and dry.json()["dry_run"] is True

    # Another run holds an unexpired lease.
    asyncio.run(live_alert_service._claim_lease("owner-x", datetime.now(timezone.utc), True))
    busy = client.post(f"{BASE}/run", headers=admin)
    assert busy.status_code == 409
    assert asyncio.run(AuditLog.find(AuditLog.action == "Live Alert Check Triggered").count()) == 3


def test_run_is_skipped_while_the_workspace_switch_is_off(client, monkeypatch):
    admin = _admin_headers(client, email="api-admin3@zs.dev")
    FakeFeed(monkeypatch)
    client.put(BASE, json={"enabled": False}, headers=admin)
    r = client.post(f"{BASE}/run", headers=admin)
    assert r.status_code == 200 and r.json()["status"] == "skipped"
    # A dry run is still allowed: previewing is how an admin decides whether to switch it on.
    assert client.post(f"{BASE}/run?dry_run=true", headers=admin).json()["status"] == "ran"


def test_status_lists_recent_alerts_without_internals(client, monkeypatch):
    admin = _admin_headers(client, email="api-admin4@zs.dev")
    owner, _, pid = _member_of(client, "recent")
    feed = FakeFeed(monkeypatch)
    _inventory(pid)
    tick(T0)
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    (row,) = client.get(BASE, headers=admin).json()["recent"]
    assert row["project_name"] == "Api recent" and row["advisory_id"] == "GHSA-aaaa-bbbb-cccc"
    assert row["severity"] == "high" and row["delivery"]["project_email"] == "off"
    assert "direct" not in str(row)  # the scanner's Direct flag is never exposed


def test_project_feed_needs_membership_and_lists_inventory_and_alerts(client, monkeypatch):
    owner, member, pid = _member_of(client, "feed")
    outsider = _headers(register_and_login(client, email="api-outsider@zs.dev"))
    assert client.get(f"/api/v1/projects/{pid}/live-alerts", headers=outsider).status_code == 403
    empty = client.get(f"/api/v1/projects/{pid}/live-alerts", headers=member).json()
    assert empty["inventories"] == [] and empty["alerts"] == [] and empty["enabled"] is True
    assert empty["effective_min_severity"] == "high" and empty["email_delivery_configured"] is False

    feed = FakeFeed(monkeypatch)
    _inventory(pid, label="example/app")
    tick(T0)
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    body = client.get(f"/api/v1/projects/{pid}/live-alerts", headers=member).json()
    assert set(body["inventories"][0]) == {
        "repo_label", "scan_type", "scanned_at", "git_commit", "dep_count", "scanner_version", "truncated"
    }
    (alert,) = body["alerts"]
    assert alert["package"] == "example-widget" and alert["version"] == "1.2.3" and alert["fixed_versions"] == ["1.2.4"]
    assert alert["locations"][0]["repo_label"] == "example/app"
    assert set(alert["delivery"]) == {"channels", "in_app", "project_webhook", "project_email"}
    assert client.get("/api/v1/projects/000000000000000000000000/live-alerts", headers=member).status_code == 404


def test_an_owners_looser_value_is_stored_but_resolves_to_the_workspace_minimum(client):
    owner, member, pid = _member_of(client, "policy")
    url = f"/api/v1/projects/{pid}/alerts"
    first = client.get(url, headers=owner).json()
    assert first["live_alert_min_severity"] is None and first["live_alert_effective"] == "high"
    assert first["workspace_live_alert_min_severity"] == "high"

    looser = client.put(url, json={"live_alert_min_severity": "medium"}, headers=owner).json()
    assert looser["live_alert_min_severity"] == "medium" and looser["live_alert_effective"] == "high"
    tighter = client.put(url, json={"live_alert_min_severity": "critical"}, headers=owner).json()
    assert tighter["live_alert_effective"] == "critical"
    off = client.put(url, json={"live_alert_min_severity": "off"}, headers=owner).json()
    assert off["live_alert_effective"] == "off"
    back = client.put(url, json={"live_alert_min_severity": "inherit"}, headers=owner).json()
    assert back["live_alert_min_severity"] is None and back["live_alert_effective"] == "high"
    # Omitting the field leaves it alone.
    client.put(url, json={"live_alert_min_severity": "critical"}, headers=owner)
    assert client.put(url, json={"email_enabled": False}, headers=owner).json()["live_alert_min_severity"] == "critical"
    assert client.put(url, json={"live_alert_min_severity": "bogus"}, headers=owner).status_code == 422
    # The same owner/admin guard as every other field: a plain member cannot change it.
    assert client.put(url, json={"live_alert_min_severity": "off"}, headers=member).status_code == 403
    assert client.get(url, headers=member).status_code == 403


def test_workspace_floor_raise_tightens_a_projects_stored_value(client):
    owner, _, pid = _member_of(client, "floor")
    admin = _admin_headers(client, email="api-admin5@zs.dev")
    url = f"/api/v1/projects/{pid}/alerts"
    client.put(url, json={"live_alert_min_severity": "medium"}, headers=owner)
    client.put(BASE, json={"min_severity": "medium"}, headers=admin)
    assert client.get(url, headers=owner).json()["live_alert_effective"] == "medium"
    client.put(BASE, json={"min_severity": "critical"}, headers=admin)
    assert client.get(url, headers=owner).json()["live_alert_effective"] == "critical"


def test_notification_catalog_shows_the_member_event_to_members_and_the_admin_event_only_to_admins(client):
    member = _headers(register_and_login(client, email="api-cat-member@zs.dev"))
    body = client.get(PREFS, headers=member).json()
    keys = {e["key"] for e in body["events"]}
    assert "dependency.new_advisory" in keys and "advisories.feed_unreachable" not in keys
    assert "dependency.new_advisory" in body["in_app"] and "dependency.new_advisory" in body["email"]
    admin = _admin_headers(client, email="api-cat-admin@zs.dev")
    admin_keys = {e["key"] for e in client.get(PREFS, headers=admin).json()["events"]}
    assert {"dependency.new_advisory", "advisories.feed_unreachable"} <= admin_keys


def _prod(**kw) -> Settings:
    return Settings(
        _env_file=None, _secrets_dir=None, app_env="production", jwt_secret="x" * 40,
        oauth_encryption_key=Fernet.generate_key().decode(), **kw,
    )


@pytest.mark.parametrize(
    "override", [{"advisory_feed_base_url": "http://127.0.0.1:8765/"}, {"osv_api_base_url": "http://127.0.0.1:8765/"}]
)
def test_production_refuses_a_non_default_feed_host(override):
    with pytest.raises(ValueError, match="only be overridden when APP_ENV=development"):
        _prod(**override)
    _prod()  # the defaults are fine
    dev = Settings(_env_file=None, _secrets_dir=None, app_env="development", jwt_secret="x" * 40, **override)
    assert dev.app_env == "development"

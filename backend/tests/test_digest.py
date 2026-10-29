"""The Teams digest: settings, preview numbers, the Adaptive Card (pure builder against a fixture),
test-send, and a scheduler that cannot double-send. OSV and webhooks are stubbed in conftest."""

import asyncio
from datetime import datetime, timedelta, timezone

from app.core.config import settings as app_settings
from app.models.digest_settings import DigestSettings
from app.models.finding import DependencyEmbedded, Finding, LocationEmbedded
from app.models.project import Project
from app.models.scan import Scan
from app.schemas.digest import (
    DigestPreview,
    DigestRow,
    DigestTotals,
    QuotaWarning,
    ScannerHealth,
    StaleProject,
)
from app.schemas.project_insights import CveRef, NewCves
from app.services import alert_service, digest_service
from tests.test_auth_flow import register_and_login
from tests.test_cloud_scan_quota import _seed
from tests.test_scans import _create_project, _headers
from tests.test_users import _admin_headers

BASE = "/api/v1/admin/digest-settings"
CHANNELS = "/api/v1/admin/webhook-channels"
HOOK = "https://example.webhook.office.com/webhookb2/secret-token-123"


def _preview_fixture() -> DigestPreview:
    t0 = datetime(2026, 10, 27, 3, 30, tzinfo=timezone.utc)
    return DigestPreview(
        period_start=t0,
        period_end=t0 + timedelta(days=1),
        rows=[
            DigestRow(
                project_id="p1",
                name="Payments",
                pipeline_runs=12,
                pipeline_failed=1,
                cloud_scans=4,
                cloud_failed=2,
                critical=3,
                high=9,
                quota_used=25,
                quota_limit=30,
                new_cves=NewCves(
                    count=3,
                    latest=[CveRef(id="CVE-2026-1234", severity="high"), CveRef(id="GHSA-xxxx-yyyy-zzzz", severity="critical")],
                ),
            ),
            DigestRow(project_id="p2", name="Ledger", pipeline_runs=2),
        ],
        totals=DigestTotals(
            pipeline_runs=14,
            pipeline_failed=1,
            cloud_scans=4,
            cloud_failed=2,
            critical=3,
            high=9,
            quota_used=25,
            quota_limit=60,
            new_cves=NewCves(count=3),
        ),
        scanner=ScannerHealth(
            engine_available=True,
            backend_scanner_version="v0.40.0",
            latest_binary_version="v0.41.0",
            outdated_ci_runners=2,
            rule_pack_version=4,
            rule_count=7,
            osv_reachable=True,
            new_cve_ids=["CVE-2026-1234", "GHSA-xxxx-yyyy-zzzz"],
        ),
        stale_projects=[StaleProject(project_id="p2", name="Ledger", last_scan_at=None)],
        quota_warnings=[QuotaWarning(project_id="p1", name="Payments", used=25, limit=30)],
    )


def _grid(card):
    """The project table: every 7-column ColumnSet, as lists of cell texts."""
    return [
        [col["items"][0]["text"] for col in b["columns"]]
        for b in card["body"]
        if b["type"] == "ColumnSet" and len(b["columns"]) == 7
    ]


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_card_builder_against_fixture():
    card = digest_service.build_card(_preview_fixture(), frontend_origin="https://portal.example")
    # 1.4 and no Table: legacy Office 365 connector webhooks silently drop newer elements.
    assert card["type"] == "AdaptiveCard" and card["version"] == "1.4"
    assert not any(n.get("type") == "Table" for n in _walk(card))

    rows = _grid(card)
    assert rows[0] == ["Project", "Pipeline", "Cloud", "Critical", "High", "Quota", "New CVEs"]
    assert rows[1] == [
        "Payments", "12 (1 failed)", "4 (2 failed)", "3", "9", "25/30", "3: CVE-2026-1234 (H), GHSA-xxxx-yyyy-zzzz (C)",
    ]
    assert rows[2][0] == "Ledger" and rows[2][-1] == "-"
    assert rows[-1] == ["Total", "14 (1 failed)", "4 (2 failed)", "3", "9", "25/60", "3"]

    [facts] = [n for n in _walk(card) if n.get("type") == "FactSet"]
    values = {f["title"]: f["value"] for f in facts["facts"]}
    assert values["Scanner in backend"] == "v0.40.0"
    assert values["Latest published binary"] == "v0.41.0"
    assert values["CI runners on an older scanner"] == "2"
    assert values["Vulnerability data"].endswith("reachable")
    text = " ".join(n.get("text", "") for n in _walk(card))
    assert "CVE-2026-1234" in text and "25/30" in text and "No scan in 30 days: Ledger" in text
    assert card["actions"][0]["url"] == "https://portal.example/admin/control-panel"


def test_card_builder_caps_the_table_but_not_the_totals():
    preview = _preview_fixture()
    preview.rows = [DigestRow(project_id=f"p{i}", name=f"P{i}") for i in range(40)]
    card = digest_service.build_card(preview)
    assert len(_grid(card)) == 1 + 25 + 1
    assert any("+ 15 more projects" in b.get("text", "") for b in card["body"])


def test_card_builder_puts_the_worst_project_first():
    preview = _preview_fixture()
    preview.rows = [
        DigestRow(project_id="a", name="Calm"),
        DigestRow(project_id="b", name="Burning", critical=5),
        DigestRow(project_id="c", name="Failing", cloud_failed=2),
    ]
    assert [r[0] for r in _grid(digest_service.build_card(preview))[1:4]] == ["Burning", "Failing", "Calm"]


# --- settings ---------------------------------------------------------------------------------


def test_settings_defaults_roundtrip_validation_and_ignored_last_fields(client):
    admin = _admin_headers(client, email="dg-admin@zs.dev")
    body = client.get(BASE, headers=admin).json()
    assert body == {
        "enabled": False, "frequency": "daily", "hour_utc": 3, "minute_utc": 30, "weekday": 0,
        "project_ids": [], "include_stale_projects": True,
        "last_sent_at": None, "last_status": None, "last_error": None,
    }
    put = {"enabled": True, "frequency": "weekly", "hour_utc": 5, "minute_utc": 0, "weekday": 2,
           "project_ids": ["x"], "include_stale_projects": False, "last_status": "sent"}
    r = client.put(BASE, json=put, headers=admin).json()
    assert r["enabled"] is True and r["weekday"] == 2 and r["last_status"] is None  # last_* ignored
    assert client.get(BASE, headers=admin).json()["hour_utc"] == 5
    assert client.put(BASE, json={**put, "hour_utc": 24}, headers=admin).status_code == 422
    assert client.put(BASE, json={**put, "frequency": "hourly"}, headers=admin).status_code == 422


def test_digest_endpoints_are_admin_only(client):
    user = _headers(register_and_login(client, email="dg-plain@zs.dev"))
    assert client.get(BASE, headers=user).status_code == 403
    assert client.get(f"{BASE}/preview", headers=user).status_code == 403
    assert client.post(f"{BASE}/send-test", headers=user).status_code == 403


# --- preview ----------------------------------------------------------------------------------


def _completed_scan_with_findings(pid, *, critical=0, high=0, age=timedelta(0)):
    async def run():
        now = datetime.now(timezone.utc) - age
        scan = Scan(project_id=pid, scan_type="cicd", status="completed", created_at=now, updated_at=now)
        await scan.insert()
        for severity, n in (("critical", critical), ("high", high)):
            for _ in range(n):
                await Finding(
                    scan_id=str(scan.id), project_id=pid, message="m", severity=severity, created_at=now,
                    location=LocationEmbedded(file="a.py"),
                ).insert()
        await Finding(
            scan_id=str(scan.id), project_id=pid, message="dep", severity="high", kind="sca", created_at=now,
            location=LocationEmbedded(file="req.txt"), dependency=DependencyEmbedded(advisory_ids=["CVE-2026-9999"]),
        ).insert()

    asyncio.run(run())


def test_preview_uses_current_exposure_counts_quota_stale_and_new_cves(client):
    owner = _headers(register_and_login(client, email="dg-owner@zs.dev"))
    pid = _create_project(client, owner, "Digest P")["id"]
    stale_pid = _create_project(client, owner, "Stale P")["id"]
    _completed_scan_with_findings(pid, critical=2, high=1, age=timedelta(hours=2))
    _completed_scan_with_findings(pid, critical=1, high=0)  # newer scan supersedes the earlier one
    _seed(pid, 25, status="failed")  # 25 of 30 cloud scans: >= 80% (failed ones do not touch exposure)

    async def age_stale():
        project = await Project.get(stale_pid)
        project.created_at = datetime.now(timezone.utc) - timedelta(days=90)
        await project.save()

    asyncio.run(age_stale())
    admin = _admin_headers(client, email="dg-preview-admin@zs.dev")

    body = client.get(f"{BASE}/preview", headers=admin).json()
    row = next(r for r in body["rows"] if r["project_id"] == pid)
    # Current exposure = the latest completed scan per repo scope, not a sum over both scans.
    assert (row["critical"], row["high"]) == (1, 1)  # newest scan: 1 critical + the dependency finding (high)
    assert row["cloud_scans"] == 25 and row["cloud_failed"] == 25 and row["quota_used"] == 25 and row["quota_limit"] == 30
    assert row["pipeline_runs"] == 2
    assert row["new_cves"]["count"] == 1 and row["new_cves"]["latest"][0]["id"] == "CVE-2026-9999"
    assert body["totals"]["cloud_scans"] == 25 and body["totals"]["new_cves"]["count"] == 1
    assert [w["project_id"] for w in body["quota_warnings"]] == [pid]
    assert [s["project_id"] for s in body["stale_projects"]] == [stale_pid]
    assert body["scanner"]["osv_reachable"] is True and body["scanner"]["new_cve_ids"] == ["CVE-2026-9999"]
    assert body["scanner"]["backend_scanner_version"] == (app_settings.scanner_build_ref or "unknown")
    assert body["scanner"]["latest_binary_version"] is None and body["scanner"]["outdated_ci_runners"] == 0
    assert set(body) == {"period_start", "period_end", "rows", "totals", "scanner", "stale_projects", "quota_warnings"}

    client.put(BASE, json={"project_ids": [pid], "include_stale_projects": False}, headers=admin)
    scoped = client.get(f"{BASE}/preview", headers=admin).json()
    assert [r["project_id"] for r in scoped["rows"]] == [pid] and scoped["stale_projects"] == []


def test_osv_unreachable_is_reported_not_fatal(client, monkeypatch):
    async def down():
        return False

    monkeypatch.setattr(digest_service, "_probe_osv", down)
    admin = _admin_headers(client, email="dg-osv@zs.dev")
    assert client.get(f"{BASE}/preview", headers=admin).json()["scanner"]["osv_reachable"] is False


# --- sending ----------------------------------------------------------------------------------


def _digest_channel(client, admin, url=HOOK, include_digest=True, enabled=True):
    r = client.post(
        CHANNELS,
        json={"name": "Daily", "url": url, "include_digest": include_digest, "enabled": enabled},
        headers=admin,
    )
    assert r.status_code == 201, r.text


def _capture_cards(monkeypatch):
    cards = []

    async def fake_post_card(url, content):
        cards.append((url, content))
        return 200

    monkeypatch.setattr(alert_service, "post_card", fake_post_card)
    monkeypatch.setattr(alert_service, "resolve_vetted_ips", lambda host: ["93.184.216.34"])
    return cards


def test_send_test_posts_the_card_to_digest_channels_only(client, monkeypatch):
    cards = _capture_cards(monkeypatch)
    admin = _admin_headers(client, email="dg-send@zs.dev")
    _digest_channel(client, admin)
    _digest_channel(client, admin, url=HOOK + "/not-digest", include_digest=False)
    _digest_channel(client, admin, url=HOOK + "/disabled", enabled=False)

    r = client.post(f"{BASE}/send-test", headers=admin).json()
    assert r == {"sent": 1, "errors": []}
    [(url, card)] = cards
    assert url == HOOK and card["version"] == "1.4" and len(_grid(card)) >= 2
    state = client.get(BASE, headers=admin).json()
    assert state["last_status"] == "sent" and state["last_sent_at"]


def test_send_test_reports_a_failing_channel_without_raising(client, monkeypatch):
    _capture_cards(monkeypatch)

    async def boom(url, content):
        raise RuntimeError(url)

    monkeypatch.setattr(alert_service, "post_card", boom)
    admin = _admin_headers(client, email="dg-send-fail@zs.dev")
    _digest_channel(client, admin)
    r = client.post(f"{BASE}/send-test", headers=admin).json()
    assert r["sent"] == 0 and len(r["errors"]) == 1 and r["errors"][0]["error"] == "RuntimeError"
    assert "secret-token" not in str(r)
    assert client.get(BASE, headers=admin).json()["last_status"] == "error"


def test_send_test_with_no_digest_channel_sends_nothing(client, monkeypatch):
    cards = _capture_cards(monkeypatch)
    admin = _admin_headers(client, email="dg-send-none@zs.dev")
    assert client.post(f"{BASE}/send-test", headers=admin).json() == {"sent": 0, "errors": []}
    assert cards == []


# --- scheduler --------------------------------------------------------------------------------


def _enable(client, admin, **overrides):
    body = {"enabled": True, "frequency": "daily", "hour_utc": 3, "minute_utc": 30, "weekday": 0, **overrides}
    assert client.put(BASE, json=body, headers=admin).status_code == 200


def test_slot_key_windows():
    d = DigestSettings(enabled=True, hour_utc=3, minute_utc=30)
    at = lambda h, m, day=28: datetime(2026, 10, day, h, m, tzinfo=timezone.utc)  # noqa: E731
    assert digest_service.slot_key(d, at(3, 29)) is None
    assert digest_service.slot_key(d, at(3, 30)) == "D:2026-10-28"
    assert digest_service.slot_key(d, at(9, 29)) == "D:2026-10-28"
    assert digest_service.slot_key(d, at(9, 31)) is None  # missed by > 6h: skipped, not sent late
    late = DigestSettings(enabled=True, hour_utc=23, minute_utc=0)
    assert digest_service.slot_key(late, at(1, 0, day=29)) == "D:2026-10-28"  # survives midnight
    weekly = DigestSettings(enabled=True, frequency="weekly", weekday=2, hour_utc=3, minute_utc=30)
    assert digest_service.slot_key(weekly, at(4, 0, day=28)) == "W:2026-10-28"  # 2026-10-28 is a Wednesday
    assert digest_service.slot_key(weekly, at(4, 0, day=27)) is None


def test_scheduler_sends_once_per_period_even_when_racing(client, monkeypatch):
    cards = _capture_cards(monkeypatch)
    admin = _admin_headers(client, email="dg-sched@zs.dev")
    _digest_channel(client, admin)
    _enable(client, admin)
    now = datetime(2026, 10, 28, 3, 40, tzinfo=timezone.utc)

    async def race():
        return await asyncio.gather(digest_service.run_due(now), digest_service.run_due(now))

    first = asyncio.run(race())
    assert sorted(first) == [False, True]
    assert asyncio.run(digest_service.run_due(now + timedelta(minutes=5))) is False
    assert len(cards) == 1
    state = client.get(BASE, headers=admin).json()
    assert state["last_status"] == "sent"

    # Next day's slot is a new period.
    assert asyncio.run(digest_service.run_due(now + timedelta(days=1))) is True
    assert len(cards) == 2


def test_scheduler_does_nothing_when_disabled_or_outside_the_slot(client, monkeypatch):
    cards = _capture_cards(monkeypatch)
    admin = _admin_headers(client, email="dg-sched-off@zs.dev")
    _digest_channel(client, admin)
    in_slot = datetime(2026, 10, 28, 3, 40, tzinfo=timezone.utc)
    _enable(client, admin, enabled=False)
    assert asyncio.run(digest_service.run_due(in_slot)) is False
    _enable(client, admin)
    assert asyncio.run(digest_service.run_due(in_slot.replace(hour=1))) is False
    assert cards == []


def test_scheduled_send_with_no_channel_records_an_error_and_audits(client, monkeypatch):
    _capture_cards(monkeypatch)
    admin = _admin_headers(client, email="dg-sched-none@zs.dev")
    _enable(client, admin)
    assert asyncio.run(digest_service.run_due(datetime(2026, 10, 28, 3, 40, tzinfo=timezone.utc))) is True
    state = client.get(BASE, headers=admin).json()
    assert state["last_status"] == "error" and "switched on" in state["last_error"]


def test_outdated_ci_runners_counts_runners_on_another_version(client):
    # The preview 500'd once a binary was published: this path only runs when `latest` is set.
    async def run():
        now = datetime.now(timezone.utc)
        for host, version in (("old-runner", "0.39.0"), ("new-runner", "v0.40.0")):
            await Scan(
                project_id="p1", scan_type="cicd", status="completed", hostname=host,
                scanner_version=version, created_at=now, updated_at=now,
            ).insert()
        return await digest_service._outdated_ci_runners("0.40.0")

    assert asyncio.run(run()) == 1

"""The Teams digest: settings, preview numbers, the Adaptive Card (pure builder against a fixture),
test-send, and a scheduler that cannot double-send. OSV and webhooks are stubbed in conftest."""

import asyncio
import json

import httpx
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
    NewAdvisory,
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
            osv_batch_ms=120,
            osv_vuln_ms=95,
            osv_checked_at=t0 + timedelta(days=1),
            last_dependency_scan_at=t0 + timedelta(hours=20),
            new_cve_ids=["CVE-2026-1234", "GHSA-xxxx-yyyy-zzzz"],
            new_advisories=[
                NewAdvisory(id="GHSA-xxxx-yyyy-zzzz", severity="critical", projects=2),
                NewAdvisory(id="CVE-2026-1234", severity="high", projects=1),
            ],
            new_advisory_count=2,
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


def _header(card):
    return card["body"][0]["items"][0]["text"]


def _title(card):
    return card["body"][0]["items"][1]["text"]


def _facts(card):
    return {f["title"]: f["value"] for n in _walk(card) if n.get("type") == "FactSet" for f in n["facts"]}


def _text_of(card):
    return " ".join(n.get("text", "") for n in _walk(card))


def _realistic_rows(n):
    return [
        DigestRow(project_id=f"p{i}", name=f"Project number {i} with a long name", pipeline_runs=12, pipeline_failed=1,
                  cloud_scans=5, critical=3, high=40, quota_used=4, quota_limit=10,
                  new_cves=NewCves(count=2, latest=[CveRef(id="CVE-2026-1234", severity="high"),
                                                    CveRef(id="GHSA-xxxx-yyyy-zzzz", severity="critical")]))
        for i in range(n)
    ]


def _cards(preview=None):
    return digest_service.build_cards(preview or _preview_fixture(), frontend_origin="https://portal.example")


def test_the_digest_is_scanner_health_then_projects_then_a_dated_summary():
    cards = _cards()
    assert [_header(c).split(" · ", 2)[2] for c in cards] == ["1/3 · SCANNER HEALTH", "2/3 · PROJECT STATUS", "3/3 · SUMMARY"]
    # 1.4 and no Table: legacy Office 365 connector webhooks silently drop newer elements.
    assert all(c["type"] == "AdaptiveCard" and c["version"] == "1.4" for c in cards)
    assert not any(n.get("type") == "Table" for c in cards for n in _walk(c))
    summary = cards[-1]
    preview = _preview_fixture()
    assert _title(summary) == f"Security digest, {preview.period_end:%a %d %b %Y}"
    assert f"Updated {preview.period_end:%H:%M} UTC" in _text_of(summary)
    assert summary["actions"][0]["url"] == "https://portal.example/admin/control-panel"


def test_health_card_reports_the_scanner_and_the_live_cve_feed():
    health = _cards()[0]
    assert _title(health) == "Scanner ready, CVE feed live" and health["body"][0]["style"] == "good"
    f = _facts(health)
    assert f["Scanner in backend"] == "v0.40.0" and f["Latest published binary"] == "v0.41.0"
    assert f["CI runners on an older scanner"] == "2" and f["Scan engine"] == "Available"
    assert f["Batch lookup"] == "reachable, 120 ms" and f["Advisory lookup"] == "reachable, 95 ms"
    assert f["Checked"] == "28 Oct 2026 03:30 UTC" and f["Last dependency scan"] == "27 Oct 2026 23:30 UTC"
    assert "no local CVE database" in f["Source"]
    text = _text_of(health)
    assert "New advisories since 27 Oct 03:30 UTC: 2" in text
    assert "GHSA-xxxx-yyyy-zzzz (critical), 2 projects" in text and "CVE-2026-1234 (high), 1 project" in text


def test_health_card_says_not_ready_when_osv_is_unreachable():
    preview = _preview_fixture()
    preview.scanner.osv_reachable = False
    preview.scanner.osv_batch_ms = None
    preview.scanner.new_advisories, preview.scanner.new_advisory_count = [], 0
    health, _projects, summary = _cards(preview)
    assert _title(health) == "Scanner NOT ready" and health["body"][0]["style"] == "attention"
    assert _facts(health)["Batch lookup"] == "NOT REACHABLE"
    assert "No advisory was first reported" in _text_of(health)
    assert "The scanner or its CVE feed is not ready" in _text_of(summary)


def test_project_card_lists_worst_first_with_a_header_row_and_no_totals_row():
    _health, projects, _summary = _cards()
    rows = _grid(projects)
    assert rows[0] == ["Project", "Pipeline", "Cloud", "Critical", "High", "Quota", "New CVEs"]
    assert rows[1] == [
        "Payments", "12 (1 failed)", "4 (2 failed)", "3", "9", "25/30", "3: CVE-2026-1234 (H), GHSA-xxxx-yyyy-zzzz (C)",
    ]
    assert rows[2][0] == "Ledger" and rows[2][-1] == "-" and len(rows) == 3
    preview = _preview_fixture()
    preview.rows = [
        DigestRow(project_id="a", name="Calm"),
        DigestRow(project_id="b", name="Burning", critical=5),
        DigestRow(project_id="c", name="Failing", cloud_failed=2),
    ]
    assert [r[0] for r in _grid(_cards(preview)[1])[1:4]] == ["Burning", "Failing", "Calm"]


def test_summary_carries_the_totals_and_what_needs_attention():
    summary = _cards()[-1]
    text = _text_of(summary)
    assert "No scan in 30 days: Ledger" in text and "Payments (25/30)" in text
    assert "1 pipeline run(s) and 2 cloud scan(s) failed" in text
    f = _facts(summary)
    assert f["Projects"] == "2" and f["Scanner"] == "Ready (v0.40.0), OSV.dev live" and f["New advisories"] == "2"


def test_projects_are_split_ten_per_card_and_every_card_fits_teams():
    preview = _preview_fixture()
    preview.rows = _realistic_rows(24)
    cards = _cards(preview)
    # 24 projects in one card was ~40 KB; Teams drops a message over ~28 KB without an error.
    assert [_title(c) for c in cards[1:-1]] == ["Projects 1-10 of 24", "Projects 11-20 of 24", "Projects 21-24 of 24"]
    assert [len(_grid(c)) - 1 for c in cards[1:-1]] == [10, 10, 4]
    assert [_header(c).split(" · ")[2] for c in cards] == ["1/5", "2/5", "3/5", "4/5", "5/5"]
    assert all(len(json.dumps(c).encode()) <= digest_service._MAX_CARD_BYTES for c in cards)


def test_projects_beyond_the_card_cap_are_named_as_left_out_but_still_in_the_totals():
    preview = _preview_fixture()
    preview.rows = _realistic_rows(75)
    cards = _cards(preview)
    assert len(cards) == 1 + digest_service._MAX_PROJECT_CARDS + 1
    assert "15 more projects were not listed on the project cards (totals include them)" in _text_of(cards[-1])
    assert _facts(cards[-1])["Projects"] == "75"


def test_no_projects_means_a_health_card_and_a_summary_only():
    preview = _preview_fixture()
    preview.rows = []
    assert [_header(c).split(" · ")[3] for c in _cards(preview)] == ["SCANNER HEALTH", "SUMMARY"]


def test_advisories_merge_across_projects_worst_severity_first():
    t = datetime(2026, 10, 28, tzinfo=timezone.utc)
    out = digest_service._advisory_summary(
        [("CVE-1", "high", t), ("CVE-1", "critical", t), ("GHSA-2", "low", t), ("CVE-3", "high", t)]
    )
    assert [(a.id, a.severity, a.projects) for a in out] == [
        ("CVE-1", "critical", 2), ("CVE-3", "high", 1), ("GHSA-2", "low", 1),
    ]


def test_live_osv_probe_times_each_endpoint_and_flags_a_5xx_or_a_network_failure():
    def ok(request):
        return httpx.Response(200, json={})

    def batch_down(request):
        return httpx.Response(503) if request.url.path.endswith("querybatch") else httpx.Response(200, json={})

    def offline(request):
        raise httpx.ConnectError("no route")

    up = asyncio.run(digest_service._probe_osv_live(transport=httpx.MockTransport(ok)))
    assert up.reachable and isinstance(up.batch_ms, int) and isinstance(up.vuln_ms, int)
    half = asyncio.run(digest_service._probe_osv_live(transport=httpx.MockTransport(batch_down)))
    assert half.batch_ms is None and half.vuln_ms is not None and not half.reachable
    down = asyncio.run(digest_service._probe_osv_live(transport=httpx.MockTransport(offline)))
    assert (down.batch_ms, down.vuln_ms, down.reachable) == (None, None, False)


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
    assert body["scanner"]["osv_batch_ms"] == 40 and body["scanner"]["osv_vuln_ms"] == 55
    assert body["scanner"]["new_advisory_count"] == 1
    assert body["scanner"]["new_advisories"] == [{"id": "CVE-2026-9999", "severity": "high", "projects": 1}]
    assert body["scanner"]["last_dependency_scan_at"]
    assert body["scanner"]["backend_scanner_version"] == (app_settings.scanner_build_ref or "unknown")
    assert body["scanner"]["latest_binary_version"] is None and body["scanner"]["outdated_ci_runners"] == 0
    assert set(body) == {"period_start", "period_end", "rows", "totals", "scanner", "stale_projects", "quota_warnings"}

    client.put(BASE, json={"project_ids": [pid], "include_stale_projects": False}, headers=admin)
    scoped = client.get(f"{BASE}/preview", headers=admin).json()
    assert [r["project_id"] for r in scoped["rows"]] == [pid] and scoped["stale_projects"] == []


def test_osv_unreachable_is_reported_not_fatal(client, monkeypatch):
    async def down():
        return digest_service.OsvProbe(batch_ms=None, vuln_ms=None, checked_at=datetime.now(timezone.utc))

    monkeypatch.setattr(digest_service, "_probe_osv", down)
    admin = _admin_headers(client, email="dg-osv@zs.dev")
    scanner = client.get(f"{BASE}/preview", headers=admin).json()["scanner"]
    assert scanner["osv_reachable"] is False and scanner["osv_batch_ms"] is None and scanner["osv_checked_at"]


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
    assert r["sent"] == 1 and r["errors"] == [] and r["cards"] == len(cards) >= 2
    assert {url for url, _ in cards} == {HOOK}  # only the digest channel
    # In order: scanner health first, the dated summary last.
    labels = [_header(card).split(" · ")[3] for _, card in cards]
    assert labels[0] == "SCANNER HEALTH" and labels[-1] == "SUMMARY"
    assert all(card["version"] == "1.4" for _, card in cards)
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
    assert r["sent"] == 0 and len(r["errors"]) == 1
    assert r["errors"][0]["error"].startswith("card 1 of ") and r["errors"][0]["error"].endswith("RuntimeError")
    assert "secret-token" not in str(r)
    assert client.get(BASE, headers=admin).json()["last_status"] == "error"


def test_send_test_with_no_digest_channel_sends_nothing(client, monkeypatch):
    cards = _capture_cards(monkeypatch)
    admin = _admin_headers(client, email="dg-send-none@zs.dev")
    assert client.post(f"{BASE}/send-test", headers=admin).json() == {"sent": 0, "errors": [], "cards": 0}
    assert cards == []


# --- scheduler --------------------------------------------------------------------------------


def _summaries(cards):
    """How many digests were posted: one dated summary card closes each."""
    return sum(1 for _, card in cards if _header(card).endswith("SUMMARY"))


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
    assert _summaries(cards) == 1
    state = client.get(BASE, headers=admin).json()
    assert state["last_status"] == "sent"

    # Next day's slot is a new period.
    assert asyncio.run(digest_service.run_due(now + timedelta(days=1))) is True
    assert _summaries(cards) == 2


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

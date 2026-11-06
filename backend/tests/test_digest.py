"""The Teams digest: settings, preview numbers, the Adaptive Cards (pure builders against a fixture),
test-send, per-project routing, and a scheduler that cannot double-send. Webhooks are stubbed in conftest."""

import asyncio
import json

from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId

from app.core.config import settings as app_settings
from app.models.digest_settings import DigestSettings
from app.models.finding import DependencyEmbedded, Finding, LocationEmbedded
from app.models.project import Project
from app.models.scan import Scan
from app.models.scanner_binary import ScannerBinary
from app.models.vulnerability import FindingReview, Vulnerability
from app.schemas.digest import (
    DigestPreview,
    DigestRow,
    DigestTotals,
    OutdatedPipeline,
    QuotaWarning,
    ScannerHealth,
    StaleProject,
)
from app.services import alert_service, digest_service
from tests.test_auth_flow import register_and_login
from tests.test_cloud_scan_quota import _seed
from tests.test_scans import _create_project, _headers
from tests.test_users import _admin_headers

BASE = "/api/v1/admin/digest-settings"
CHANNELS = "/api/v1/admin/webhook-channels"
HOOK = "https://example.webhook.office.com/webhookb2/secret-token-123"


def _outdated(project="Payments", repo="github.com/acme/pay (runner-1)", version="0.38.0", runs=5):
    return OutdatedPipeline(
        project_id="p1", project=project, repository=repo, scanner_version=version, runs=runs,
        last_run_at=datetime(2026, 10, 27, 22, 5, tzinfo=timezone.utc),
    )


def _preview_fixture() -> DigestPreview:
    t0 = datetime(2026, 10, 27, 3, 30, tzinfo=timezone.utc)
    return DigestPreview(
        period_start=t0,
        period_end=t0 + timedelta(days=1),
        rows=[
            DigestRow(
                project_id="p1", name="Payments", pipeline_runs=12, pipeline_failed=1, cloud_scans=4, cloud_failed=2,
                critical=3, high=9, resolved=7, new_findings=5, false_positives=1, vulnerabilities=4,
            ),
            DigestRow(project_id="p2", name="Ledger", pipeline_runs=2),
        ],
        totals=DigestTotals(pipeline_runs=14, pipeline_failed=1, cloud_scans=4, cloud_failed=2, critical=3, high=9),
        scanner=ScannerHealth(
            engine_available=True,
            backend_scanner_version="v0.40.0",
            latest_binary_version="v0.41.0",
            projects_outdated=1,
            outdated_pipelines=[_outdated(), _outdated(project="Ledger", version="0.39.0", runs=2)],
            new_advisory_count=2,
        ),
        stale_projects=[StaleProject(project_id="p2", name="Ledger", last_scan_at=None)],
        quota_warnings=[QuotaWarning(project_id="p1", name="Payments", used=25, limit=30)],
    )


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _grid(card, columns=8):
    """A table of the card: every ColumnSet with this many columns, as lists of cell texts."""
    return [
        [col["items"][0]["text"] for col in n["columns"]]
        for n in _walk(card)
        if n.get("type") == "ColumnSet" and len(n["columns"]) == columns
    ]


def _header(card):
    return card["body"][0]["items"][0]["text"]


def _title(card):
    return card["body"][0]["items"][1]["text"]


def _facts(card):
    return {f["title"]: f["value"] for n in _walk(card) if n.get("type") == "FactSet" for f in n["facts"]}


def _text_of(card):
    return " ".join(n.get("text", "") for n in _walk(card))


def _kpis(card):
    """(caption, value) of every KPI tile: an ExtraLarge number over a subtle caption."""
    return [
        (n["items"][1]["text"], n["items"][0]["text"])
        for n in _walk(card)
        if n.get("type") == "Column" and n["items"][0].get("size") == "ExtraLarge"
    ]


def _realistic_rows(n):
    return [
        DigestRow(project_id=f"p{i}", name=f"Project number {i} with a long name", pipeline_runs=12, pipeline_failed=1,
                  cloud_scans=5, critical=3, high=40, resolved=120, new_findings=33)
        for i in range(n)
    ]


def _cards(preview=None):
    return digest_service.build_cards(preview or _preview_fixture(), frontend_origin="https://portal.example")


def _fits(card):
    return len(json.dumps(card).encode()) <= digest_service._MAX_CARD_BYTES


def test_the_digest_is_scanner_then_projects_then_a_dated_summary():
    cards = _cards()
    assert [_header(c).split(" · ", 2)[2] for c in cards] == ["1/3 · SCANNER", "2/3 · PROJECT STATUS", "3/3 · SUMMARY"]
    # 1.4 and no Table: legacy Office 365 connector webhooks silently drop newer elements.
    assert all(c["type"] == "AdaptiveCard" and c["version"] == "1.4" for c in cards)
    assert not any(n.get("type") == "Table" for c in cards for n in _walk(c))
    summary = cards[-1]
    preview = _preview_fixture()
    assert _title(summary) == f"Security digest, {preview.period_end:%a %d %b %Y}"
    assert f"Updated {preview.period_end:%H:%M} UTC" in _text_of(summary)
    assert summary["actions"][0]["url"] == "https://portal.example/admin/control-panel"


def test_scanner_card_has_the_five_facts_and_no_osv_section():
    scanner = _cards()[0]
    assert _title(scanner) == "Scanner ready" and scanner["body"][0]["style"] == "good"
    assert _facts(scanner) == {
        "Scanner in backend": "v0.40.0",
        "Latest published binary": "v0.41.0",
        "Projects on an older scanner": "1",
        "New CVEs added": "2",
        "Scan engine": "Available",
    }
    text = _text_of(scanner)
    assert "OSV" not in text and "CVE data" not in text and "New advisories" not in text and "Rule pack" not in text


def test_scanner_card_lists_outdated_pipelines_and_says_not_ready_without_the_engine():
    preview = _preview_fixture()
    preview.scanner.engine_available = False
    scanner = _cards(preview)[0]
    assert _title(scanner) == "Scanner NOT ready" and scanner["body"][0]["style"] == "attention"
    assert _facts(scanner)["Scan engine"] == "NOT AVAILABLE"
    rows = _grid(scanner, 5)
    assert rows[0] == ["Project", "Repository", "Scanner used", "Runs", "Last run (UTC)"]
    assert rows[1] == ["Payments", "github.com/acme/pay (runner-1)", "0.38.0", "5", "27 Oct 2026 22:05"]
    assert rows[2][0] == "Ledger" and len(rows) == 3


def test_outdated_table_is_capped_and_has_its_two_empty_states():
    preview = _preview_fixture()
    preview.scanner.outdated_pipelines = [_outdated(repo=f"github.com/acme/r{i}") for i in range(18)]
    scanner = _cards(preview)[0]
    assert len(_grid(scanner, 5)) - 1 == digest_service._MAX_OUTDATED_ROWS == 15
    assert "+ 3 more." in _text_of(scanner)

    preview.scanner.outdated_pipelines = []
    assert "Every pipeline in this period used v0.41.0." in _text_of(_cards(preview)[0])
    assert _grid(_cards(preview)[0], 5) == []

    preview.scanner.latest_binary_version = None
    assert "No scanner binary is published" in _text_of(_cards(preview)[0])


def test_project_card_lists_worst_first_with_fail_rate_resolved_and_new_findings():
    _scanner, projects, _summary = _cards()
    rows = _grid(projects)
    assert rows[0] == ["Project", "CI/CD", "Cloud", "Critical", "High", "Fail rate", "Resolved", "New findings"]
    # 3 failed of 16 scans = 18.75%.
    assert rows[1] == ["Payments", "12", "4", "3", "9", "19%", "7", "5"]
    assert rows[2] == ["Ledger", "2", "0", "0", "0", "0%", "0", "0"] and len(rows) == 3
    text = _text_of(projects)
    assert "Quota" not in text and "New CVEs" not in text
    preview = _preview_fixture()
    preview.rows = [
        DigestRow(project_id="a", name="Calm"),
        DigestRow(project_id="b", name="Burning", critical=5),
        DigestRow(project_id="c", name="Failing", cloud_failed=2, cloud_scans=2),
    ]
    graded = _grid(_cards(preview)[1])
    assert [r[0] for r in graded[1:4]] == ["Burning", "Failing", "Calm"]
    assert graded[3][5] == "-" and graded[2][5] == "100%"  # no scans: "-"; all failed: 100%


def test_summary_has_exactly_three_kpis_and_nothing_else():
    summary = _cards()[-1]
    assert _kpis(summary) == [("CI/CD SCANS", "14"), ("CLOUD SCANS", "4"), ("FAILED SCANS", "3")]
    text = _text_of(summary)
    assert not _facts(summary) and "Needs attention" not in text and "Scanner" not in text
    assert summary["actions"][0]["title"] == "Open Control Panel"


def test_projects_are_split_ten_per_card_and_every_card_fits_teams():
    preview = _preview_fixture()
    preview.rows = _realistic_rows(24)
    cards = _cards(preview)
    # 24 projects in one card was ~40 KB; Teams drops a message over ~28 KB without an error.
    assert [_title(c) for c in cards[1:-1]] == ["Projects 1-10 of 24", "Projects 11-20 of 24", "Projects 21-24 of 24"]
    assert [len(_grid(c)) - 1 for c in cards[1:-1]] == [10, 10, 4]
    assert [_header(c).split(" · ")[2] for c in cards] == ["1/5", "2/5", "3/5", "4/5", "5/5"]
    assert all(_fits(c) for c in cards)


def test_projects_beyond_the_card_cap_are_named_as_left_out_but_still_in_the_totals():
    preview = _preview_fixture()
    preview.rows = _realistic_rows(75)
    cards = _cards(preview)
    assert len(cards) == 1 + digest_service._MAX_PROJECT_CARDS + 1
    assert "15 more projects were not listed on the project cards (totals include them)" in _text_of(cards[-1])
    assert all(_fits(c) for c in cards)


def test_no_projects_means_a_scanner_card_and_a_summary_only():
    preview = _preview_fixture()
    preview.rows = []
    assert [_header(c).split(" · ")[3] for c in _cards(preview)] == ["SCANNER", "SUMMARY"]


def test_the_worst_case_scanner_card_fits_teams():
    preview = _preview_fixture()
    preview.scanner.outdated_pipelines = [
        _outdated(project=f"Project number with a long name {i}", repo="github.com/acme/" + "x" * 60 + f" (runner-{i})")
        for i in range(200)
    ]
    assert _fits(_cards(preview)[0])


def test_project_digest_card_has_the_six_figures_and_nothing_about_other_projects():
    cards = digest_service.build_project_cards(_preview_fixture(), frontend_origin="https://portal.example")
    assert [_title(c) for c in cards] == ["Payments", "Ledger"]
    assert [_header(c).split(" · ", 2)[2] for c in cards] == ["1/2 · PROJECT DIGEST", "2/2 · PROJECT DIGEST"]
    pay = cards[0]
    assert _kpis(pay) == [("TOTAL SCANS", "16"), ("CI/CD SCANS", "12"), ("CLOUD SCANS", "4"), ("FAILED SCANS", "3")]
    # 1 false positive of 4 vulnerabilities = 25%; resolved is all-time.
    assert _facts(pay) == {"Resolved (all time)": "7", "False-positive rate": "25%"}
    assert "Ledger" not in _text_of(pay) and "Scanner" not in _text_of(pay)
    assert _facts(cards[1])["False-positive rate"] == "-"  # no vulnerabilities at all
    assert pay["actions"][0]["url"] == "https://portal.example/projects/p1"
    assert all(c["version"] == "1.4" and _fits(c) for c in cards)


def test_percent_math():
    assert digest_service._pct(1, 4) == "25%" and digest_service._pct(0, 5) == "0%" and digest_service._pct(3, 0) == "-"
    assert digest_service._pct(1, 3) == "33%" and digest_service._pct(2, 3) == "67%"


def test_versions_sort_numerically_and_ignore_a_leading_v():
    versions = ["v0.10.0", "0.9.0", "v0.2.1"]
    assert sorted(versions, key=digest_service._version_key) == ["v0.2.1", "0.9.0", "v0.10.0"]


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


def _vuln(pid, n, *, status="open", reason=None, review=None, first_seen=None):
    async def run():
        seen = first_seen or datetime.now(timezone.utc)
        await Vulnerability(
            project_id=pid, repo_scope_key="unlinked", fingerprint=f"fp-{pid}-{n}-{status}-{reason}-{review}",
            status=status, resolution_reason=reason, review=review, first_seen_at=seen, last_seen_at=seen,
        ).insert()

    asyncio.run(run())


def _review(kind, status):
    return FindingReview(
        kind=kind, status=status, file_path="a.py", requested_by_user_id="u1",
        requested_at=datetime.now(timezone.utc), request_comment="c",
    )


def test_preview_uses_current_exposure_counts_stale_and_new_cves_and_vulnerability_figures(client):
    owner = _headers(register_and_login(client, email="dg-owner@zs.dev"))
    pid = _create_project(client, owner, "Digest P")["id"]
    stale_pid = _create_project(client, owner, "Stale P")["id"]
    _completed_scan_with_findings(pid, critical=2, high=1, age=timedelta(hours=2))
    _completed_scan_with_findings(pid, critical=1, high=0)  # newer scan supersedes the earlier one
    _seed(pid, 25, status="failed")  # 25 of 30 cloud scans: >= 80% (failed ones do not touch exposure)
    long_ago = datetime.now(timezone.utc) - timedelta(days=40)
    # 6 vulnerabilities: 2 resolved (one as a false positive), an accepted false-positive review, a
    # pending one (not counted), a plain open one, and an old one first seen outside the period.
    _vuln(pid, 1, status="resolved", reason="fixed")
    _vuln(pid, 2, status="resolved", reason="false_positive")
    _vuln(pid, 3, status="accepted_risk", review=_review("false_positive", "accepted"))
    _vuln(pid, 4, review=_review("false_positive", "pending"))
    _vuln(pid, 5)
    _vuln(pid, 6, status="resolved", reason="fixed", first_seen=long_ago)
    _vuln(stale_pid, 1)

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
    assert row["cloud_scans"] == 25 and row["cloud_failed"] == 25 and row["pipeline_runs"] == 2
    assert row["resolved"] == 3  # all-time, including the one first seen 40 days ago
    assert row["new_findings"] == 5  # first seen inside the period
    assert (row["false_positives"], row["vulnerabilities"]) == (2, 6)  # resolved-as and accepted-review
    other = next(r for r in body["rows"] if r["project_id"] == stale_pid)
    assert (other["resolved"], other["new_findings"], other["vulnerabilities"]) == (0, 1, 1)
    assert body["totals"] == {
        "pipeline_runs": 2, "pipeline_failed": 0, "cloud_scans": 25, "cloud_failed": 25, "critical": 1, "high": 1,
    }
    assert [w["project_id"] for w in body["quota_warnings"]] == [pid]
    assert [s["project_id"] for s in body["stale_projects"]] == [stale_pid]
    assert body["scanner"] == {
        "engine_available": body["scanner"]["engine_available"],
        "backend_scanner_version": app_settings.scanner_build_ref or "unknown",
        "latest_binary_version": None,
        "projects_outdated": 0,
        "outdated_pipelines": [],
        "new_advisory_count": 1,  # CVE-2026-9999, counted once
    }
    assert set(body) == {"period_start", "period_end", "rows", "totals", "scanner", "stale_projects", "quota_warnings"}

    client.put(BASE, json={"project_ids": [pid], "include_stale_projects": False}, headers=admin)
    scoped = client.get(f"{BASE}/preview", headers=admin).json()
    assert [r["project_id"] for r in scoped["rows"]] == [pid] and scoped["stale_projects"] == []


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
    # In order: scanner first, the dated summary last.
    labels = [_header(card).split(" · ")[3] for _, card in cards]
    assert labels[0] == "SCANNER" and labels[-1] == "SUMMARY"
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


def _cicd_scan(pid, version, *, repo="https://github.com/acme/pay.git", host="runner-1", age=timedelta(hours=1), kind="cicd"):
    async def run():
        at = datetime.now(timezone.utc) - age
        await Scan(
            project_id=pid, scan_type=kind, status="completed", hostname=host, repo_url=repo,
            scanner_version=version, created_at=at, updated_at=at,
        ).insert()

    asyncio.run(run())


def _publish_binary(version):
    async def run():
        await ScannerBinary(
            version=version, os="linux", arch="amd64", filename="zerostrike", gridfs_file_id=PydanticObjectId(),
            sha256="0" * 64, size_bytes=1, uploaded_at=datetime.now(timezone.utc), uploaded_by="qa",
        ).insert()

    asyncio.run(run())


def test_outdated_pipelines_are_period_scoped_grouped_and_exclude_up_to_date_runs(client):
    owner = _headers(register_and_login(client, email="dg-outdated@zs.dev"))
    p1 = _create_project(client, owner, "Old Scanner P")["id"]
    p2 = _create_project(client, owner, "Older Scanner P")["id"]
    p3 = _create_project(client, owner, "Current P")["id"]
    _publish_binary("0.41.0")
    for hours in (1, 2, 3):  # one group: same project + repo + host + version
        _cicd_scan(p1, "0.39.0", repo="https://x-token:s3cr3t@github.com/acme/pay.git", age=timedelta(hours=hours))
    _cicd_scan(p1, "v0.41.0", repo="https://github.com/acme/ok")  # up to date (a leading v does not matter)
    _cicd_scan(p1, "0.30.0", age=timedelta(days=3))  # before the period
    _cicd_scan(p1, "0.30.0", kind="cloud")  # not a pipeline
    _cicd_scan(p2, "0.38.0", repo="https://github.com/acme/ledger", host="runner-9")
    _cicd_scan(p3, "0.41.0")
    admin = _admin_headers(client, email="dg-outdated-admin@zs.dev")

    scanner = client.get(f"{BASE}/preview", headers=admin).json()["scanner"]
    assert scanner["latest_binary_version"] == "0.41.0" and scanner["projects_outdated"] == 2
    assert [(o["project"], o["repository"], o["scanner_version"], o["runs"]) for o in scanner["outdated_pipelines"]] == [
        ("Older Scanner P", "github.com/acme/ledger (runner-9)", "0.38.0", 1),  # oldest version first
        ("Old Scanner P", "github.com/acme/pay.git (runner-1)", "0.39.0", 3),
    ]
    assert "s3cr3t" not in str(scanner) and scanner["outdated_pipelines"][1]["last_run_at"]


def test_nothing_is_outdated_without_a_published_binary(client):
    owner = _headers(register_and_login(client, email="dg-nobin@zs.dev"))
    pid = _create_project(client, owner, "No Binary P")["id"]
    _cicd_scan(pid, "0.1.0")
    admin = _admin_headers(client, email="dg-nobin-admin@zs.dev")
    scanner = client.get(f"{BASE}/preview", headers=admin).json()["scanner"]
    assert scanner["outdated_pipelines"] == [] and scanner["projects_outdated"] == 0


# --- per-project routing ----------------------------------------------------------------------


def _scoped_channel(client, admin, project_ids, url):
    r = client.post(
        CHANNELS,
        json={"name": "Scoped", "url": url, "include_digest": True, "project_ids": project_ids},
        headers=admin,
    )
    assert r.status_code == 201, r.text


def test_a_scoped_channel_gets_one_card_per_project_and_not_the_global_digest(client, monkeypatch):
    cards = _capture_cards(monkeypatch)
    owner = _headers(register_and_login(client, email="dg-scope-owner@zs.dev"))
    mine = _create_project(client, owner, "Scoped Mine")["id"]
    _create_project(client, owner, "Someone Elses")
    _completed_scan_with_findings(mine, critical=1)
    _vuln(mine, 1, status="resolved", reason="false_positive")
    _vuln(mine, 2)
    admin = _admin_headers(client, email="dg-scope-admin@zs.dev")
    _scoped_channel(client, admin, [mine], HOOK + "/scoped")
    _digest_channel(client, admin, url=HOOK + "/global")

    r = client.post(f"{BASE}/send-test", headers=admin).json()
    assert r["sent"] == 2 and r["errors"] == []
    scoped = [c for url, c in cards if url.endswith("/scoped")]
    global_ = [c for url, c in cards if url.endswith("/global")]
    # The scoped channel: exactly its project's card. No scanner card, no summary, no other project.
    assert [_header(c).split(" · ")[3] for c in scoped] == ["PROJECT DIGEST"]
    assert _title(scoped[0]) == "Scoped Mine"
    assert _facts(scoped[0]) == {"Resolved (all time)": "1", "False-positive rate": "50%"}
    assert "Someone Elses" not in " ".join(_text_of(c) for c in scoped)
    # The unscoped channel: the global digest, which lists every project.
    labels = [_header(c).split(" · ")[3] for c in global_]
    assert labels[0] == "SCANNER" and labels[-1] == "SUMMARY"
    assert "Someone Elses" in " ".join(_text_of(c) for c in global_)
    assert all(_fits(c) for _url, c in cards)


def test_a_scoped_channel_whose_projects_are_gone_reports_an_error_not_a_green_send(client, monkeypatch):
    cards = _capture_cards(monkeypatch)
    admin = _admin_headers(client, email="dg-scope-gone@zs.dev")
    _scoped_channel(client, admin, ["a" * 24], HOOK + "/scoped")
    r = client.post(f"{BASE}/send-test", headers=admin).json()
    assert r["sent"] == 0 and "no active project" in r["errors"][0]["error"] and cards == []


def test_the_scheduler_sends_a_scoped_channel_its_project_card(client, monkeypatch):
    cards = _capture_cards(monkeypatch)
    owner = _headers(register_and_login(client, email="dg-scope-sched-owner@zs.dev"))
    mine = _create_project(client, owner, "Sched Mine")["id"]
    admin = _admin_headers(client, email="dg-scope-sched@zs.dev")
    _scoped_channel(client, admin, [mine], HOOK + "/scoped")
    _enable(client, admin)
    assert asyncio.run(digest_service.run_due(datetime(2026, 10, 28, 3, 40, tzinfo=timezone.utc))) is True
    assert [_title(c) for _url, c in cards] == ["Sched Mine"]
    assert client.get(BASE, headers=admin).json()["last_status"] == "sent"

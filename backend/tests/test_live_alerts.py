"""Live dependency alerts: inventory ingestion and the watcher engine (docs/LIVE_DEPENDENCY_ALERTS.md).

The OSV feed is replaced by `FakeFeed`, which implements the two network functions the real service
exposes (`_get`, `_post`) at the HTTP level, Range requests included, so the real chunking and parsing
code runs. No test reaches the network, a webhook or an SMTP server; every name is synthetic."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx
import pytest
import structlog

from app.core import advisory as adv
from app.core.config import settings as app_settings
from app.core.security import encrypt_secret
from app.models.advisory_watch_state import AdvisoryWatchState
from app.models.audit_log import AuditLog
from app.models.dependency_inventory import DependencyInventory, InventoryDep
from app.models.finding import DependencyEmbedded, Finding, LocationEmbedded
from app.models.live_dependency_alert import LiveDependencyAlert
from app.models.notification import Notification
from app.models.project import Project
from app.models.scan import Scan
from app.models.vulnerability import FindingReview, Vulnerability
from app.schemas.report import GoReportIn
from app.services import (
    advisory_feed_service,
    alert_service,
    email_service,
    live_alert_service,
    webhook_channel_service,
    workspace_settings_service,
)
from app.services import report_ingestion_service as ingest_svc
from tests.test_auth_flow import register_and_login
from tests.test_scans import _create_project, _headers
from tests.test_users import _admin_headers

T0 = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(hours=1)
FIXTURE = Path(__file__).parent / "fixtures" / "go_report_with_inventory.json"
HOOK = "https://example.invalid/hooks/secret-token-123"
CHANNELS = "/api/v1/admin/webhook-channels"


def run(coro):
    return asyncio.run(coro)


def iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeFeed:
    """An in-memory OSV: per-ecosystem modified index (Range-capable), records, and querybatch."""

    def __init__(self, monkeypatch):
        self.rows: dict[str, list[tuple[datetime, str]]] = {e: [] for e in adv.SUPPORTED_ECOSYSTEMS}
        self.records: dict[tuple[str, str], dict] = {}
        self.matches: dict[tuple[str, str, str], list[str]] = {}
        self.down = False
        self.confirm_down = False
        self.bad_records: set[str] = set()
        self.post_calls = 0
        monkeypatch.setattr(advisory_feed_service, "_get", self.get)
        monkeypatch.setattr(advisory_feed_service, "_post", self.post)

    def publish(
        self, eco="npm", advisory_id="GHSA-aaaa-bbbb-cccc", *, modified, published=None, package="example-widget",
        versions=("1.2.3",), severity="HIGH", aliases=("CVE-2026-0001",), fixed="1.2.4", matches=()
    ):
        """Add (or re-publish under a later `modified`) one record. `matches` are (package, version) pairs
        that only OSV's range matcher would know are affected (querybatch), not the explicit list."""
        self.records[(eco, advisory_id)] = {
            "id": advisory_id,
            "aliases": list(aliases),
            "summary": "Synthetic advisory",
            "published": iso(published or modified - timedelta(minutes=5)),
            "modified": iso(modified),
            "database_specific": {"severity": severity} if severity else {},
            "affected": [
                {
                    "package": {"ecosystem": eco, "name": package},
                    "versions": list(versions),
                    "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": fixed}]}],
                }
            ],
        }
        self.rows[eco].append((modified, advisory_id))
        for pkg, version in [*[(package, v) for v in versions], *matches]:
            self.matches.setdefault((eco, pkg, version), []).append(advisory_id)

    def _index(self, eco: str) -> str:
        return "".join(f"{iso(m)},{i}\n" for m, i in sorted(self.rows[eco], reverse=True))

    async def get(self, url, headers=None):
        if self.down:
            raise httpx.ConnectError("feed down")
        eco, name = urlsplit(url).path.strip("/").split("/", 1)
        if name == "modified_id.csv":
            body = self._index(eco).encode()
            start, end = (int(x) for x in headers["Range"].removeprefix("bytes=").split("-"))
            if start >= len(body) and start > 0:
                return 416, b""
            return 206, body[start : end + 1]
        advisory_id = unquote(name).removesuffix(".json")
        if advisory_id in self.bad_records:
            return 500, b""
        record = self.records.get((eco, advisory_id))
        return (200, json.dumps(record).encode()) if record else (404, b"")

    async def post(self, url, payload):
        self.post_calls += 1
        if self.down or self.confirm_down:
            raise httpx.ConnectError("osv down")
        results = []
        for q in payload["queries"]:
            key = (q["package"]["ecosystem"], q["package"]["name"], q["version"])
            results.append({"vulns": [{"id": i} for i in self.matches.get(key, [])]})
        return 200, {"results": results}


@pytest.fixture()
def posts(monkeypatch):
    """Every webhook post is recorded instead of sent; DNS vetting is stubbed."""
    sent = []

    async def fake_post_webhook(url, title, text, link=None, facts=None, **style):
        sent.append({"url": url, "title": title, "text": text, "link": link, "facts": facts, **style})
        return 200

    monkeypatch.setattr(alert_service, "post_webhook", fake_post_webhook)
    monkeypatch.setattr(alert_service, "resolve_vetted_ips", lambda host: ["93.184.216.34"])
    return sent


# --- builders ---------------------------------------------------------------------------------


def _setup(client, tag):
    owner = register_and_login(client, email=f"owner-{tag}@zs.dev")
    headers = _headers(owner)
    return headers, _create_project(client, headers, name=f"Live {tag}")["id"]


def _inventory(pid, deps=(("npm", "example-widget", "1.2.3"),), *, scanned_at=None, scope="__unlinked__", label="example/app", scan_type="cloud"):
    async def go():
        await DependencyInventory(
            project_id=pid,
            repo_scope_key=scope,
            repo_label=label,
            scan_id=f"scan-{scope}",
            scan_type=scan_type,
            git_commit="0123456789abcdef",
            scanned_at=scanned_at or T0 - timedelta(days=1),
            dep_count=len(deps),
            deps=[
                InventoryDep(k=adv.dep_key(e, p), ecosystem=e, package=p, version=v, manifests=["package-lock.json"], direct=True)
                for e, p, v in deps
            ],
        ).insert()

    run(go())


async def _go(**kwargs):
    kwargs.setdefault("force", True)
    summary = await live_alert_service.run_once(**kwargs)
    await webhook_channel_service.drain()
    return summary


def tick(now, **kwargs):
    return run(_go(now=now, **kwargs))


def _ledger(pid=None):
    async def go():
        query = LiveDependencyAlert.find(LiveDependencyAlert.project_id == pid) if pid else LiveDependencyAlert.find()
        return await query.to_list()

    return run(go())


def _state():
    return run(live_alert_service.get_state())


def _env(client, monkeypatch, tag, deps=(("npm", "example-widget", "1.2.3"),)):
    """A project with an inventory, a fake feed, and the first (baseline) run done at T0."""
    headers, pid = _setup(client, tag)
    feed = FakeFeed(monkeypatch)
    _inventory(pid, deps)
    assert tick(T0).status == "ran"
    return headers, pid, feed


# --- inventory ingestion ----------------------------------------------------------------------


def _ingest(pid, payload):
    report = GoReportIn.model_validate(payload)

    async def go():
        now = datetime.now(timezone.utc)
        scan = Scan(project_id=pid, scan_type="cicd", created_at=now, updated_at=now)
        await scan.insert()
        await ingest_svc.ingest(scan, report, raw_json=json.dumps(payload))

    run(go())


def _inventories(pid):
    return run(DependencyInventory.find(DependencyInventory.project_id == pid).to_list())


def test_report_with_dependencies_stores_one_merged_snapshot(client):
    _, pid = _setup(client, "inv1")
    _ingest(pid, json.loads(FIXTURE.read_text()))
    (inv,) = _inventories(pid)
    assert inv.dep_count == 3 and not inv.truncated and inv.scan_type == "cicd"
    assert inv.git_commit.startswith("0123456") and inv.repo_scope_key == "__unlinked__"
    widget = next(d for d in inv.deps if d.package == "example-widget")
    assert widget.k == "npm|example-widget"
    # The clone-workdir prefix is stripped, and the same package in two manifests is one dependency.
    assert widget.manifests == ["package-lock.json", "web/package-lock.json"]
    assert {d.k for d in inv.deps} == {"npm|example-widget", "PyPI|example-widget-py", "Go|example.invalid/mod"}


def test_the_stored_raw_report_does_not_carry_the_package_list_a_second_time(client):
    from app.models.report import Report

    _, pid = _setup(client, "inv-raw")
    payload = json.loads(FIXTURE.read_text())
    _ingest(pid, payload)
    (inv,) = _inventories(pid)
    assert inv.dep_count == 3  # the inventory is the one stored copy
    (stored,) = run(Report.find(Report.project_id == pid).to_list())
    kept = json.loads(stored.raw_json)
    assert "Dependencies" not in kept
    assert set(kept) == set(payload) - {"Dependencies"}  # everything else is untouched
    # A report without an inventory (older scanner) is stored exactly as received.
    older = {k: v for k, v in payload.items() if k != "Dependencies"}
    _, pid2 = _setup(client, "inv-raw2")
    _ingest(pid2, older)
    (stored2,) = run(Report.find(Report.project_id == pid2).to_list())
    assert stored2.raw_json == json.dumps(older)


def test_report_without_the_key_keeps_the_previous_inventory_and_empty_list_replaces_it(client):
    _, pid = _setup(client, "inv2")
    payload = json.loads(FIXTURE.read_text())
    _ingest(pid, payload)
    payload.pop("Dependencies")  # an older scanner, or a run without --enable-sca
    _ingest(pid, payload)
    (inv,) = _inventories(pid)
    assert inv.dep_count == 3
    _ingest(pid, {**payload, "Dependencies": None})  # Go marshals a nil slice as null: still "no info"
    assert _inventories(pid)[0].dep_count == 3
    _ingest(pid, {**payload, "Dependencies": []})  # SCA ran and found nothing: a real, empty inventory
    (inv,) = _inventories(pid)
    assert inv.dep_count == 0 and inv.deps == []


# --- first run, new advisory, dedupe ----------------------------------------------------------


def test_first_run_sets_cursors_and_alerts_nothing(client, monkeypatch):
    _, pid = _setup(client, "first")
    feed = FakeFeed(monkeypatch)
    _inventory(pid)
    feed.publish(modified=T0 - timedelta(minutes=5))  # already in the feed before the watcher ever ran
    assert tick(T0).status == "ran"
    assert _ledger() == []
    cursors = _state().cursors
    assert cursors["npm"] == T0 - timedelta(minutes=5) and cursors["PyPI"] == T0
    # Still nothing on the next run: the advisory is at or behind the cursor.
    tick(T1)
    assert _ledger() == []


def test_new_matching_advisory_alerts_once_grouped_per_project(client, monkeypatch, posts):
    headers, pid, feed = _env(client, monkeypatch, "grp", deps=(("npm", "example-widget", "1.2.3"), ("PyPI", "Example_Py", "2.0.0")))
    admin = _admin_headers(client, email="admin-grp@zs.dev")
    r = client.post(CHANNELS, json={"name": "Feed", "url": HOOK, "events": ["dependency.new_advisory"]}, headers=admin)
    assert r.status_code == 201, r.text
    feed.publish("npm", "GHSA-aaaa-bbbb-cccc", modified=T0 + timedelta(minutes=20))
    feed.publish("PyPI", "PYSEC-2026-9", modified=T0 + timedelta(minutes=30), package="example-py", versions=("2.0.0",), severity="CRITICAL", aliases=())

    summary = tick(T1)
    assert summary.alerts == 2 and summary.projects_alerted == 1
    rows = _ledger(pid)
    assert {r.advisory_id for r in rows} == {"GHSA-aaaa-bbbb-cccc", "PYSEC-2026-9"}
    # One grouped message, not one per advisory.
    assert len(posts) == 1 and posts[0]["title"] == "Live grp: 2 new dependency advisories (1 critical, 1 high)"
    assert posts[0]["tone"] == "attention" and posts[0]["eyebrow"] == "New dependency advisory"
    note = run(Notification.find(Notification.event == "dependency.new_advisory").to_list())
    assert len(note) == 1 and note[0].project_id == pid and note[0].severity == "error"
    assert all(r.delivery.channels == 1 and r.delivery.in_app == 1 for r in rows)
    # The alert is a ledger row, never a Finding.
    assert run(Finding.find(Finding.project_id == pid).count()) == 0

    posts.clear()
    tick(T1 + timedelta(hours=1))
    tick(T1 + timedelta(hours=2))
    assert len(_ledger(pid)) == 2 and posts == []


def test_an_alias_from_another_database_does_not_alert_again(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "alias")
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    assert len(_ledger(pid)) == 1
    feed.publish("npm", "PYSEC-2026-77", modified=T1 + timedelta(minutes=20), aliases=("CVE-2026-0001",))
    tick(T1 + timedelta(hours=1))
    assert len(_ledger(pid)) == 1


def test_old_advisory_modified_today_does_not_alert(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "old")
    feed.publish(modified=T0 + timedelta(minutes=20), published=T0 - timedelta(days=10))
    tick(T1)
    assert _ledger(pid) == [] and posts == []


def test_withdrawn_and_low_severity_advisories_are_skipped(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "skip")
    feed.publish("npm", "GHSA-wwww-wwww-wwww", modified=T0 + timedelta(minutes=20))
    feed.records[("npm", "GHSA-wwww-wwww-wwww")]["withdrawn"] = iso(T0 + timedelta(minutes=21))
    feed.publish("npm", "GHSA-llll-llll-llll", modified=T0 + timedelta(minutes=25), severity="LOW", aliases=())
    tick(T1)
    assert _ledger(pid) == []


def test_widened_range_alerts_only_the_newly_matching_version(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "wide", deps=(("npm", "example-widget", "1.2.3"), ("npm", "example-widget", "1.3.0")))
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    assert [r.version for r in _ledger(pid)] == ["1.2.3"]
    # The advisory is edited (same published date, later modified) to cover 1.3.0 as well.
    feed.publish(modified=T1 + timedelta(minutes=20), published=T0 + timedelta(minutes=15), matches=(("example-widget", "1.3.0"),))
    tick(T1 + timedelta(hours=1))
    assert sorted(r.version for r in _ledger(pid)) == ["1.2.3", "1.3.0"]


def test_range_only_match_is_confirmed_by_querybatch(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "range", deps=(("npm", "example-widget", "1.9.0"),))
    feed.publish(modified=T0 + timedelta(minutes=20), versions=(), matches=(("example-widget", "1.9.0"),))
    tick(T1)
    assert [r.version for r in _ledger(pid)] == ["1.9.0"] and feed.post_calls == 1
    # A candidate OSV does not confirm is not an alert.
    _, pid2, feed2 = _env(client, monkeypatch, "range2", deps=(("npm", "example-widget", "9.9.9"),))
    feed2.publish(modified=T0 + timedelta(minutes=20), versions=())
    tick(T1)
    assert _ledger(pid2) == []


def test_package_a_scan_already_reported_is_skipped(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "known")

    async def seed():
        await Finding(
            scan_id="s1", project_id=pid, message="m", severity="high", kind="sca", created_at=T0,
            location=LocationEmbedded(file="package-lock.json"),
            dependency=DependencyEmbedded(package="example-widget", advisory_ids=["CVE-2026-0001"]),
        ).insert()

    run(seed())
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    assert _ledger(pid) == []


def test_accepted_exemption_suppresses_the_alert(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "exempt")

    async def seed():
        await Vulnerability(
            project_id=pid, repo_scope_key="__unlinked__",
            fingerprint=adv.sca_fingerprint("npm", "example-widget", "GHSA-aaaa-bbbb-cccc"),
            first_seen_at=T0, last_seen_at=T0,
            review=FindingReview(kind="accepted_risk", status="accepted", file_path="package-lock.json",
                                 requested_by_user_id="u1", requested_at=T0, request_comment="accepted"),
        ).insert()

    run(seed())
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    assert _ledger(pid) == []


def test_archived_project_stale_inventory_and_projects_without_one_are_skipped(client, monkeypatch, posts):
    headers, archived = _setup(client, "arch")
    other_headers, stale = _setup(client, "stale")
    _, none_pid = _setup(client, "none")
    feed = FakeFeed(monkeypatch)
    _inventory(archived)
    _inventory(stale, scanned_at=T1 - timedelta(days=200))
    tick(T0)

    async def archive():
        project = await Project.get(archived)
        project.is_archived = True
        await project.save()

    run(archive())
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    assert _ledger() == []
    del headers, other_headers, none_pid


def test_one_message_per_project_across_ecosystems_in_one_run(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "multi", deps=(("npm", "example-widget", "1.2.3"), ("Go", "example.invalid/mod", "v1.0.0")))
    feed.publish("npm", modified=T0 + timedelta(minutes=20))
    feed.publish("Go", "GO-2026-5", modified=T0 + timedelta(minutes=25), package="example.invalid/mod", versions=("v1.0.0",), aliases=())
    summary = tick(T1)
    assert summary.ecosystems["npm"]["status"] == "ok" and summary.ecosystems["Go"]["status"] == "ok"
    assert len(_ledger(pid)) == 2


# --- failures and cursors ---------------------------------------------------------------------


def test_querybatch_failure_leaves_the_cursor_and_the_next_run_retries(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "qb", deps=(("npm", "example-widget", "1.9.0"),))
    feed.publish(modified=T0 + timedelta(minutes=20), versions=(), matches=(("example-widget", "1.9.0"),))
    feed.confirm_down = True
    summary = tick(T1)
    assert summary.ecosystems["npm"]["status"] == "error"
    state = _state()
    assert state.cursors["npm"] == T0 and state.last_status == "partial"
    assert _ledger(pid) == []  # a failure never alerts a project
    feed.confirm_down = False
    tick(T1 + timedelta(hours=1))
    assert len(_ledger(pid)) == 1 and _state().last_status == "ok"


def test_record_fetch_error_advances_only_to_the_last_good_row(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "err")
    feed.publish("npm", "GHSA-aaaa-bbbb-cccc", modified=T0 + timedelta(minutes=10))
    feed.publish("npm", "GHSA-good-good-good", modified=T0 + timedelta(minutes=20), package="unrelated", versions=("1.0.0",), aliases=())
    feed.publish("npm", "GHSA-boom-boom-boom", modified=T0 + timedelta(minutes=30), aliases=())
    feed.bad_records.add("GHSA-boom-boom-boom")
    tick(T1)
    assert _state().cursors["npm"] == T0 + timedelta(minutes=20)
    assert [r.advisory_id for r in _ledger(pid)] == ["GHSA-aaaa-bbbb-cccc"]  # the good row before it was handled
    feed.bad_records.clear()
    tick(T1 + timedelta(hours=1))
    assert {r.advisory_id for r in _ledger(pid)} == {"GHSA-aaaa-bbbb-cccc", "GHSA-boom-boom-boom"}


def test_downtime_beyond_the_catchup_clamps_the_cursor_and_records_a_gap(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "gap")
    later = T0 + timedelta(days=5)
    feed.publish(modified=T0 + timedelta(minutes=20))  # inside the lost window: not alerted
    tick(later)
    state = _state()
    assert state.last_gap_hours == pytest.approx(48.0) and state.last_gap_at == later
    assert state.cursors["npm"] == later - timedelta(minutes=app_settings.advisory_settle_minutes)
    assert _ledger(pid) == []
    audit = run(AuditLog.find(AuditLog.action == "Advisory Watch Gap Skipped").to_list())
    assert audit and all(a.actor_type == "system" for a in audit)


def test_project_threshold_filters_and_cannot_loosen(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "thr")

    async def set_min(value):
        project = await Project.get(pid)
        project.live_alert_min_severity = value
        await project.save()

    run(set_min("critical"))  # tighter than the workspace's "high"
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    assert _ledger(pid) == []
    run(set_min("off"))
    feed.publish("npm", "GHSA-crit-crit-crit", modified=T1 + timedelta(minutes=20), severity="CRITICAL", aliases=())
    tick(T1 + timedelta(hours=1))
    assert _ledger(pid) == []
    # "medium" is looser than the workspace's "high": stored, but resolved to "high".
    run(set_min("medium"))
    policy = run(workspace_settings_service.effective_live_alert_policy(run(Project.get(pid))))
    assert policy.min_severity == "high" and policy.enabled and not policy.overridden


def test_toggle_off_then_on_resets_cursors_so_nothing_is_backfilled(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "toggle")
    admin = _admin_headers(client, email="admin-toggle@zs.dev")
    base = "/api/v1/admin/live-alerts"
    assert client.put(base, json={"enabled": False}, headers=admin).status_code == 200
    feed.publish(modified=T0 + timedelta(minutes=20))  # published while alerts were off
    assert tick(T1).status == "skipped"
    assert client.put(base, json={"enabled": True}, headers=admin).status_code == 200
    assert _state().cursors == {}
    tick(T1 + timedelta(hours=1))  # first run again: baseline only
    assert _ledger(pid) == []


# --- lease ------------------------------------------------------------------------------------


def test_two_concurrent_runs_only_one_runs(client, monkeypatch, posts):
    _setup(client, "race")
    FakeFeed(monkeypatch)

    async def race():
        return await asyncio.gather(_go(now=T0, force=False), _go(now=T0, force=False))

    assert sorted(s.status for s in run(race())) == ["busy", "ran"]
    assert run(AdvisoryWatchState.find().count()) == 1  # the singleton stayed a singleton

    # Even a forced run cannot start while another run holds an unexpired lease.
    async def held():
        assert await live_alert_service._claim_lease("owner-x", T1, True) is not None
        return await live_alert_service.run_once(now=T1 + timedelta(minutes=1), force=True)

    assert run(held()).status == "busy"


def test_run_not_due_yet_is_busy_unless_forced(client, monkeypatch):
    _setup(client, "due")
    FakeFeed(monkeypatch)
    assert tick(T0, force=False).status == "ran"
    assert tick(T0 + timedelta(minutes=10), force=False).status == "busy"
    assert tick(T0 + timedelta(minutes=61), force=False).status == "ran"


def test_expired_lease_is_reclaimable_and_a_stale_owner_cannot_move_a_cursor(client, monkeypatch):
    _setup(client, "lease")
    FakeFeed(monkeypatch)

    async def go():
        assert await live_alert_service._claim_lease("owner-a", T0, True) is not None
        assert await live_alert_service._claim_lease("owner-b", T0 + timedelta(minutes=5), True) is None  # still held
        assert await live_alert_service._claim_lease("owner-b", T0 + timedelta(minutes=20), True) is not None
        assert await live_alert_service._set_cursor("owner-a", "npm", T1) is False
        assert await live_alert_service._set_cursor("owner-b", "npm", T1) is True

    run(go())
    assert _state().cursors["npm"] == T1


# --- feed health ------------------------------------------------------------------------------


def test_feed_unreachable_alerts_admins_once_per_outage_and_resets_on_success(client, monkeypatch, posts):
    admin = _admin_headers(client, email="admin-down@zs.dev")
    admin_id = client.get("/api/v1/auth/me", headers=admin).json()["id"]
    feed = FakeFeed(monkeypatch)
    monkeypatch.setattr(app_settings, "advisory_feed_unreachable_alert_hours", 6)
    feed.down = True

    def alerts():
        return run(Notification.find(Notification.user_id == admin_id, Notification.event == "advisories.feed_unreachable").to_list())

    assert tick(T0).status == "ran" and alerts() == []  # not down long enough yet
    assert _state().last_status == "error" and _state().failing_since == T0
    tick(T0 + timedelta(hours=7))
    assert len(alerts()) == 1
    tick(T0 + timedelta(hours=8))
    tick(T0 + timedelta(hours=9))
    assert len(alerts()) == 1 and _state().consecutive_failures == 4
    assert run(AuditLog.find(AuditLog.action == "Advisory Watch Failed").count()) == 1
    assert "feed down" not in (_state().last_error or "") and "http" not in (_state().last_error or "").lower()

    feed.down = False
    tick(T0 + timedelta(hours=10))
    state = _state()
    assert state.last_status == "ok" and state.failing_since is None and state.unreachable_alerted_at is None
    assert state.consecutive_failures == 0 and state.last_success_at == T0 + timedelta(hours=10)


# --- dry run ----------------------------------------------------------------------------------


def test_dry_run_claims_nothing_and_returns_previews(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "dry")
    feed.publish(modified=T0 + timedelta(minutes=20))
    before = _state()
    summary = tick(T1, dry_run=True)
    assert summary.status == "ran" and summary.dry_run and summary.alerts == 1
    (preview,) = summary.previews
    assert preview["project_id"] == pid and 0 < preview["bytes"] < 12 * 1024
    assert preview["card"]["type"] == "AdaptiveCard"
    assert _ledger(pid) == [] and posts == []
    after = _state()
    assert after.cursors == before.cursors and after.last_run_started_at == before.last_run_started_at
    assert run(Notification.find(Notification.event == "dependency.new_advisory").count()) == 0
    tick(T1)  # the real run still finds it: the dry run claimed nothing
    assert len(_ledger(pid)) == 1


# --- routing and delivery ---------------------------------------------------------------------


def _project_channels(pid, *, webhook=True, email=False):
    async def go():
        project = await Project.get(pid)
        if webhook:
            project.alert_webhook_enc = encrypt_secret("https://example.invalid/project-hook/abc")
            project.alert_webhook_enabled = True
        if email:
            project.alert_email_enabled = True
            project.alert_emails = ["ops@example.invalid"]
        await project.save()

    run(go())


def test_routes_to_subscribed_channels_and_the_projects_own_webhook(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "route")
    admin = _admin_headers(client, email="admin-route@zs.dev")
    sub = client.post(CHANNELS, json={"name": "Subscribed", "url": HOOK, "events": ["dependency.new_advisory"]}, headers=admin)
    other = client.post(CHANNELS, json={"name": "Other", "url": "https://example.invalid/other", "events": ["scan.completed"]}, headers=admin)
    assert sub.status_code == 201 and other.status_code == 201
    _project_channels(pid)
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    urls = sorted(p["url"] for p in posts)
    assert urls == sorted([HOOK, "https://example.invalid/project-hook/abc"])
    (row,) = _ledger(pid)
    assert row.delivery.channels == 1 and row.delivery.project_webhook == "sent" and row.delivery.project_email == "off"
    # The project's own webhook carries a link, never the advisory text.
    own = next(p for p in posts if p["url"].endswith("/abc"))
    assert own["link"] == f"/projects/{pid}?tab=overview&src=alert" and "Synthetic advisory" not in own["text"]


def test_email_outcome_is_honest(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "mail", deps=(("npm", "example-widget", "1.2.3"),))
    _project_channels(pid, webhook=False, email=True)
    sent = []
    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: sent.append(a))
    feed.publish("npm", "GHSA-aaaa-bbbb-cccc", modified=T0 + timedelta(minutes=20))
    tick(T1)
    assert _ledger(pid)[0].delivery.project_email == "not_configured"
    assert not [a for a in sent if a[0] == "ops@example.invalid"]  # SMTP unset: never attempted for the project

    monkeypatch.setattr(app_settings, "smtp_host", "smtp.example.invalid")

    def refuse(*a, **k):
        raise RuntimeError("525 refused")

    monkeypatch.setattr(email_service, "send_email", refuse)
    feed.publish("npm", "GHSA-bbbb-cccc-dddd", modified=T1 + timedelta(minutes=20), package="example-widget", versions=("1.2.3",), aliases=("CVE-2026-0002",))
    # A second advisory for the same version is a different ledger row.
    tick(T1 + timedelta(hours=1))
    failed = next(r for r in _ledger(pid) if r.advisory_id == "GHSA-bbbb-cccc-dddd")
    assert failed.delivery.project_email == "failed"

    monkeypatch.setattr(email_service, "send_email", lambda *a, **k: sent.append(a))
    feed.publish("npm", "GHSA-cccc-dddd-eeee", modified=T1 + timedelta(hours=1, minutes=20), aliases=("CVE-2026-0003",))
    tick(T1 + timedelta(hours=2))
    ok = next(r for r in _ledger(pid) if r.advisory_id == "GHSA-cccc-dddd-eeee")
    assert ok.delivery.project_email == "sent" and [a for a in sent if a[0] == "ops@example.invalid"]


def test_delivery_failure_logs_a_warning_never_an_error(client, monkeypatch):
    _, pid, feed = _env(client, monkeypatch, "warn")
    _project_channels(pid)

    async def boom(*a, **k):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(alert_service, "post_webhook", boom)
    monkeypatch.setattr(alert_service, "resolve_vetted_ips", lambda host: ["93.184.216.34"])
    feed.publish(modified=T0 + timedelta(minutes=20))
    with structlog.testing.capture_logs() as logs:
        tick(T1)
    levels = {entry["log_level"] for entry in logs}
    assert "warning" in levels and not levels & {"error", "critical"}
    assert _ledger(pid)[0].delivery.project_webhook == "failed"  # recorded, not "sent"


def test_audit_rows_are_system_actor_and_project_scoped(client, monkeypatch, posts):
    _, pid, feed = _env(client, monkeypatch, "audit")
    _project_channels(pid)
    feed.publish(modified=T0 + timedelta(minutes=20))
    tick(T1)
    (row,) = run(AuditLog.find(AuditLog.action == "Live Dependency Alert Raised").to_list())
    assert row.actor_type == "system" and row.actor_user_id is None and row.project_id == pid
    assert row.metadata["advisories"] == ["GHSA-aaaa-bbbb-cccc"] and row.metadata["project_webhook"] == "sent"
    blob = json.dumps(row.metadata)
    assert "http" not in blob and "@" not in blob


def _ledger_row(**overrides):
    fields = dict(
        project_id="p1", advisory_id="GHSA-aaaa-bbbb-cccc", advisory_ids=["GHSA-aaaa-bbbb-cccc", "CVE-2026-1111"],
        summary="Prototype pollution in synthetic-lib allows remote code execution", ecosystem="npm",
        package="synthetic-lib", package_norm="synthetic-lib", version="1.0.0", severity="high", cvss_score=8.1,
        published_at=T0, fixed_versions=["1.0.4", "2.0.1"],
    )
    return LiveDependencyAlert(**{**fields, **overrides})


def test_alert_fact_carries_severity_cvss_fix_version_and_impact():
    message = adv.build_alert("Payments", "p1", [_ledger_row()], T0 + timedelta(minutes=30))
    fact = dict(message.facts)["GHSA-aaaa-bbbb-cccc · CVE-2026-1111"]
    assert fact.startswith("HIGH 8.1 · synthetic-lib 1.0.0 -> fix 1.0.4 · Prototype pollution in synthetic-lib")
    assert "remote code execution" in fact


def test_alert_fact_says_no_fix_yet_and_truncates_a_long_impact():
    row = _ledger_row(fixed_versions=[], summary="word " * 80, cvss_score=None, severity="critical")
    fact = dict(adv.build_alert("Payments", "p1", [row], T0 + timedelta(minutes=30)).facts)[
        "GHSA-aaaa-bbbb-cccc · CVE-2026-1111"
    ]
    assert fact.startswith("CRITICAL · synthetic-lib 1.0.0 -> no fix yet · word word")
    impact = fact.split(" · ")[2]
    assert impact.endswith("...") and len(impact) == adv._MAX_IMPACT
    # A missing summary adds no empty part, and the advisory's `details` is never read.
    bare = dict(adv.build_alert("Payments", "p1", [_ledger_row(summary="")], T0).facts)["GHSA-aaaa-bbbb-cccc · CVE-2026-1111"]
    assert "·  ·" not in bare and bare.split(" · ")[:2] == ["HIGH 8.1", "synthetic-lib 1.0.0 -> fix 1.0.4"]

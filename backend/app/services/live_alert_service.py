"""Live dependency advisory alerts: the watcher (docs/LIVE_DEPENDENCY_ALERTS.md, algorithm in section 6).

Every `advisory_watch_interval_minutes` one run reads each ecosystem's OSV index since its cursor, keeps
the advisories published in the last 72 hours that are serious enough, finds the projects whose stored
dependency inventory contains an affected package, and alerts each such project once with one grouped
message. The pure rules (is it new, how bad, what does the card say) live in core/advisory.py; the feed
I/O in advisory_feed_service.

Properties that must not be softened:
- At most once: the ledger row (unique per project/package/version/advisory) is inserted BEFORE delivery,
  so a crash, a second replica or a retry can skip an alert but never repeat one.
- A failure never alerts a project and never moves a cursor past rows that were not processed.
- Every state write after the lease is taken is conditioned on `lease_owner == run_id`.
- Delivery failures log at WARNING only: ERROR is what `portal.error` alerts on, and an alert about
  alerting must not alert about itself.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import structlog
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.core import advisory as adv_core
from app.core.config import settings
from app.core.timeutils import as_utc
from app.models.advisory_watch_state import STATE_KEY, AdvisoryWatchState
from app.models.dependency_inventory import DependencyInventory
from app.models.finding import Finding
from app.models.live_dependency_alert import AlertDelivery, AlertLocation, LiveDependencyAlert
from app.models.project import Project
from app.models.vulnerability import Vulnerability
from app.models.webhook_channel import WebhookChannel
from app.schemas.live_alerts import (
    EcosystemLag,
    InventoryCoverage,
    LiveAlertDeliveryOut,
    LiveAlertLocationOut,
    LiveAlertRow,
    LiveAlertStatus,
    ProjectInventoryOut,
    ProjectLiveAlerts,
)
from app.services import (
    advisory_feed_service as feed,
    alert_service,
    audit_service,
    dependency_inventory_service,
    notification_service,
    webhook_channel_service,
    workspace_settings_service,
)

logger = structlog.get_logger(__name__)

_LEASE = timedelta(minutes=15)
_RECORD_CONCURRENCY = 8
_MIN_INTERVAL_MINUTES = 15
_CARD_EYEBROW = "New dependency advisory"


class LeaseLost(Exception):
    """This run no longer owns the lease: stop without writing anything more."""


@dataclass
class RunSummary:
    status: str  # ran | busy | skipped
    dry_run: bool = False
    run_id: str | None = None
    reason: str | None = None
    records: int = 0
    qualified: int = 0
    matched: int = 0
    alerts: int = 0
    projects_alerted: int = 0
    ecosystems: dict[str, dict] = field(default_factory=dict)
    previews: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "reason": self.reason,
            "records": self.records,
            "qualified": self.qualified,
            "matched": self.matched,
            "alerts": self.alerts,
            "projects_alerted": self.projects_alerted,
            "ecosystems": self.ecosystems,
        }


@dataclass
class _Run:
    now: datetime
    dry_run: bool
    run_id: str | None
    ws: object
    state: AdvisoryWatchState
    summary: RunSummary
    new_rows: dict[str, list[LiveDependencyAlert]] = field(default_factory=dict)
    seen: set[tuple] = field(default_factory=set)
    projects: dict[str, Project | None] = field(default_factory=dict)
    policies: dict[str, object] = field(default_factory=dict)
    gap_hours: float | None = None


def _describe(exc: Exception) -> str:
    """A reason that can never carry a URL (httpx puts it in str(exc))."""
    return str(exc)[:200] if isinstance(exc, feed.FeedError) else type(exc).__name__


def _interval() -> timedelta:
    return timedelta(minutes=max(_MIN_INTERVAL_MINUTES, settings.advisory_watch_interval_minutes))


# --- state and lease --------------------------------------------------------------------------


def _state_collection():
    return AdvisoryWatchState.get_pymongo_collection()


async def get_state() -> AdvisoryWatchState:
    """The singleton, created on first use. The upsert is keyed on the unique `key`, so two replicas racing
    here cannot produce two documents (the loser's DuplicateKeyError just means it already exists)."""
    try:
        await _state_collection().update_one({"key": STATE_KEY}, {"$setOnInsert": {"cursors": {}}}, upsert=True)
    except DuplicateKeyError:
        pass
    state = await AdvisoryWatchState.find_one({"key": STATE_KEY})
    assert state is not None
    return state


async def _claim_lease(run_id: str, now: datetime, force: bool) -> AdvisoryWatchState | None:
    await get_state()
    conditions: list[dict] = [{"$or": [{"lease_until": None}, {"lease_until": {"$lt": now}}]}]
    if not force:
        conditions.append(
            {"$or": [{"last_run_started_at": None}, {"last_run_started_at": {"$lte": now - _interval()}}]}
        )
    raw = await _state_collection().find_one_and_update(
        {"key": STATE_KEY, "$and": conditions},
        {"$set": {"lease_owner": run_id, "lease_until": now + _LEASE, "last_run_started_at": now}},
        return_document=ReturnDocument.AFTER,
    )
    return AdvisoryWatchState.model_validate(raw) if raw else None


async def _set(run_id: str, fields: dict) -> None:
    """Write state only while this run still holds the lease."""
    result = await _state_collection().update_one(
        {"key": STATE_KEY, "lease_owner": run_id}, {"$set": {**fields, "updated_at": datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        raise LeaseLost()


async def _set_cursor(run_id: str, ecosystem: str, cursor: datetime) -> bool:
    try:
        await _set(run_id, {f"cursors.{ecosystem}": cursor})
    except LeaseLost:
        return False
    return True


async def _release(run_id: str) -> None:
    await _state_collection().update_one(
        {"key": STATE_KEY, "lease_owner": run_id}, {"$set": {"lease_owner": None, "lease_until": None}}
    )


async def reset_cursors() -> None:
    """Forget every cursor, so the next run records the feed head and alerts nothing. Used when an admin
    turns the workspace switch back on: whatever was published while it was off is not backfilled."""
    await get_state()
    await _state_collection().update_one({"key": STATE_KEY}, {"$set": {"cursors": {}}})


# --- the run ----------------------------------------------------------------------------------


async def run_once(*, now: datetime | None = None, force: bool = False, dry_run: bool = False) -> RunSummary:
    now = now or datetime.now(timezone.utc)
    ws = await workspace_settings_service.get_workspace_settings()
    if not settings.advisory_watch_enabled:
        return RunSummary("skipped", dry_run, reason="Advisory watching is disabled by ADVISORY_WATCH_ENABLED")
    if not ws.live_alerts_enabled and not dry_run:
        return RunSummary("skipped", dry_run, reason="Live dependency alerts are switched off")

    summary = RunSummary("ran", dry_run)
    if dry_run:
        # Read-only: no lease, no state write, no ledger row, no delivery.
        state = await get_state()
        run = _Run(now, True, None, ws, state, summary)
    else:
        run_id = uuid.uuid4().hex
        state = await _claim_lease(run_id, now, force)
        if state is None:
            return RunSummary("busy", dry_run, reason="Another run holds the lease, or one ran recently")
        summary.run_id = run_id
        run = _Run(now, False, run_id, ws, state, summary)

    try:
        failures: dict[str, str] = {}
        for ecosystem in adv_core.SUPPORTED_ECOSYSTEMS:
            try:
                await _process_ecosystem(run, ecosystem)
            except LeaseLost:
                raise
            except Exception as exc:
                failures[ecosystem] = _describe(exc)
                summary.ecosystems.setdefault(ecosystem, {})["status"] = "error"
                summary.ecosystems[ecosystem]["error"] = failures[ecosystem]
                logger.warning("advisory ecosystem failed", ecosystem=ecosystem, error=failures[ecosystem], exc_info=True)

        await _deliver_all(run)
        if not dry_run:
            await _feed_health(run, failures)
    except LeaseLost:
        summary.status = "busy"
        summary.reason = "The run lost its lease and stopped"
        logger.warning("advisory run lost its lease", run_id=run.run_id)
    finally:
        if run.run_id:
            await _release(run.run_id)
    return summary


async def _process_ecosystem(run: _Run, ecosystem: str) -> None:
    now, summary = run.now, run.summary
    stats = summary.ecosystems.setdefault(ecosystem, {"status": "ok"})
    cursor = as_utc(run.state.cursors.get(ecosystem))

    # First run never backfills: record where the feed is now and alert nothing.
    if cursor is None:
        head = await feed.head_modified(ecosystem)
        stats["status"] = "first_run"
        if not run.dry_run:
            await _set_cursor(run.run_id, ecosystem, head or now) or _lost()
        return

    # Downtime longer than the catch-up window: look back no further than the floor and say so.
    floor = now - timedelta(hours=settings.advisory_catchup_hours)
    if cursor < floor:
        await _record_gap(run, ecosystem, (floor - cursor).total_seconds() / 3600)
        cursor = floor
        if not run.dry_run:
            await _set_cursor(run.run_id, ecosystem, cursor) or _lost()

    horizon = now - timedelta(minutes=settings.advisory_settle_minutes)
    rows, reached = await feed.fetch_rows_since(ecosystem, cursor, horizon)
    if not reached:
        # More changed than the walk could cover: the oldest rows are beyond reach. Process what we have.
        await _record_gap(run, ecosystem, (horizon - cursor).total_seconds() / 3600)
    rows.sort(key=lambda r: r[0])
    truncated = len(rows) > settings.advisory_max_records_per_run
    rows = rows[: settings.advisory_max_records_per_run]
    stats["records"] = len(rows)
    summary.records += len(rows)

    semaphore = asyncio.Semaphore(_RECORD_CONCURRENCY)

    async def fetch(advisory_id: str):
        async with semaphore:
            try:
                return "ok", await feed.fetch_record(ecosystem, advisory_id)
            except Exception as exc:
                return "error", exc

    results = await asyncio.gather(*(fetch(advisory_id) for _, advisory_id in rows))

    max_age = timedelta(hours=settings.advisory_max_age_hours)
    qualified: list[adv_core.Advisory] = []
    good_until: datetime | None = None  # modified of the last row fully processed before any failure
    failed_at: datetime | None = None
    error: Exception | None = None
    for (modified, _), (outcome, payload) in zip(rows, results):
        if outcome == "error":
            failed_at, error = modified, payload
            break
        # A tie with the failed row is re-read next run (the ledger makes that harmless), so only rows
        # strictly older than the failure advance the cursor.
        good_until = modified
        if payload is None:
            continue  # 404: the index lists a record the bucket does not (yet) have
        advisory = adv_core.normalize_advisory(payload, ecosystem)
        if _qualifies(advisory, run.ws, now, max_age):
            qualified.append(advisory)
    summary.qualified += len(qualified)

    if qualified:
        await _match_and_claim(run, ecosystem, qualified)

    if error is not None:
        stats["status"] = "error"
        stats["error"] = _describe(error)
        safe = max((m for m, _ in rows if m < failed_at and (good_until is None or m <= good_until)), default=None)
        if safe is not None and safe > cursor and not run.dry_run:
            await _set_cursor(run.run_id, ecosystem, safe) or _lost()
        raise error
    if run.dry_run:
        return
    # Complete: every row at or before the horizon is handled. (Advancing only to the newest processed row
    # would let a quiet ecosystem such as NuGet drift past the catch-up floor and report a false gap.)
    target = good_until if truncated else horizon
    if target is not None and target > cursor:
        await _set_cursor(run.run_id, ecosystem, target) or _lost()


def _lost():
    raise LeaseLost()


def _qualifies(advisory: adv_core.Advisory, ws, now: datetime, max_age: timedelta) -> bool:
    if advisory.withdrawn or not advisory.affected or not adv_core.is_new(advisory, now, max_age):
        return False
    if advisory.malicious:
        return bool(ws.live_alerts_include_malicious)
    return adv_core.severity_meets(advisory.severity, ws.live_alerts_min_severity)


async def _record_gap(run: _Run, ecosystem: str, hours: float) -> None:
    run.gap_hours = hours
    run.summary.ecosystems.setdefault(ecosystem, {})["gap_hours"] = round(hours, 1)
    if run.dry_run:
        return
    await _set(run.run_id, {"last_gap_at": run.now, "last_gap_hours": round(hours, 1)})
    await _audit(
        "Advisory Watch Gap Skipped", None, {"ecosystem": ecosystem, "skipped_hours": round(hours, 1)}
    )


async def _project(run: _Run, project_id: str) -> Project | None:
    if project_id not in run.projects:
        project = await workspace_settings_service.load_project(project_id)
        run.projects[project_id] = None if project is None or project.is_archived else project
    return run.projects[project_id]


async def _match(run: _Run, ecosystem: str, qualified: list[adv_core.Advisory]) -> list[tuple]:
    """(inventory, dep, advisory) for every inventory dependency confirmed affected. Candidates come from
    the `deps.k` index; a version in the record's explicit list is confirmed locally, every other
    candidate goes to OSV's own matcher in ONE querybatch. A confirm() failure raises: nothing is
    alerted and the cursor stays put, so the next run retries."""
    keys = list({adv_core.dep_key(ecosystem, a.name) for adv in qualified for a in adv.affected})
    inventories = await DependencyInventory.find({"deps.k": {"$in": keys}}).to_list()
    oldest = run.now - timedelta(days=settings.live_alert_inventory_max_age_days)
    by_key: dict[str, list[tuple]] = {}
    for inv in inventories:
        if (as_utc(inv.scanned_at) or run.now) < oldest or await _project(run, inv.project_id) is None:
            continue
        for dep in inv.deps:
            if dep.version and dep.ecosystem == ecosystem:
                by_key.setdefault(dep.k, []).append((inv, dep))

    candidates: dict[tuple, tuple] = {}
    for advisory in qualified:
        for affected in advisory.affected:
            for inv, dep in by_key.get(adv_core.dep_key(ecosystem, affected.name), []):
                ident = (str(inv.id), dep.k, dep.version, advisory.id)
                local = dep.version in affected.versions
                if ident not in candidates or (local and not candidates[ident][3]):
                    candidates[ident] = (inv, dep, advisory, local)
    if not candidates:
        return []

    pending = {(dep.ecosystem, dep.package, dep.version) for _, dep, _, local in candidates.values() if not local}
    answers = await feed.confirm(sorted(pending)) if pending else {}
    confirmed = []
    for inv, dep, advisory, local in candidates.values():
        if local or answers.get((dep.ecosystem, dep.package, dep.version), set()) & set(advisory.ids):
            confirmed.append((inv, dep, advisory))
    return confirmed


async def _match_and_claim(run: _Run, ecosystem: str, qualified: list[adv_core.Advisory]) -> None:
    confirmed = await _match(run, ecosystem, qualified)
    run.summary.matched += len(confirmed)

    # One row per (project, advisory, package version); the same package in several repos merges its locations.
    grouped: dict[tuple, dict] = {}
    for inv, dep, advisory in confirmed:
        entry = grouped.setdefault(
            (inv.project_id, advisory.id, dep.k, dep.version), {"advisory": advisory, "dep": dep, "locations": []}
        )
        entry["locations"].append(
            AlertLocation(
                repo_scope_key=inv.repo_scope_key,
                repo_label=inv.repo_label,
                manifests=dep.manifests[:5],
                direct=dep.direct,
                inventory_scan_id=inv.scan_id,
                inventory_scanned_at=as_utc(inv.scanned_at),
                git_commit=inv.git_commit,
            )
        )
    for (project_id, _, _, _), entry in grouped.items():
        project = await _project(run, project_id)
        if project is None:
            continue
        row = await _claim_alert(run, project, entry["advisory"], entry["dep"], entry["locations"])
        if row is not None:
            run.new_rows.setdefault(project_id, []).append(row)


async def _claim_alert(
    run: _Run, project: Project, advisory: adv_core.Advisory, dep, locations: list[AlertLocation]
) -> LiveDependencyAlert | None:
    """Apply the project's policy and the three "already known" checks, then claim by inserting the
    ledger row. Returns the row if THIS run now owns the alert, else None."""
    project_id = str(project.id)
    if project_id not in run.policies:
        run.policies[project_id] = await workspace_settings_service.effective_live_alert_policy(project)
    policy = run.policies[project_id]
    if not policy.enabled:
        return None
    if advisory.malicious:
        if not policy.include_malicious:
            return None
    elif not adv_core.severity_meets(advisory.severity, policy.min_severity):
        return None

    # A scan already reported this advisory for this package: the findings flow owns it.
    if await Finding.find(
        {
            "project_id": project_id,
            "kind": "sca",
            "dependency.package": dep.package,
            "dependency.advisory_ids": {"$in": list(advisory.ids)},
        }
    ).count():
        return None
    # An admin accepted the risk for exactly this dependency finding.
    if await Vulnerability.find_one(
        {
            "project_id": project_id,
            "fingerprint": adv_core.sca_fingerprint(dep.ecosystem, dep.package, advisory.id),
            "review.status": "accepted",
        }
    ):
        return None

    norm = adv_core.normalize_package_name(dep.ecosystem, dep.package)
    in_run = {(project_id, dep.ecosystem, norm, dep.version, i) for i in advisory.ids}
    if in_run & run.seen:
        return None
    # The same advisory under another database's id (GHSA vs CVE vs PYSEC) was already alerted.
    if await LiveDependencyAlert.find_one(
        {
            "project_id": project_id,
            "ecosystem": dep.ecosystem,
            "package_norm": norm,
            "version": dep.version,
            "advisory_ids": {"$in": list(advisory.ids)},
        }
    ):
        return None
    run.seen |= in_run

    fixed = next((a.fixed for a in advisory.affected if a.name_norm == norm and a.fixed), ())
    row = LiveDependencyAlert(
        project_id=project_id,
        advisory_id=advisory.id,
        advisory_ids=list(advisory.ids),
        summary=advisory.summary,
        ecosystem=dep.ecosystem,
        package=dep.package,
        package_norm=norm,
        version=dep.version,
        severity=advisory.severity,
        cvss_score=advisory.cvss_score,
        malicious=advisory.malicious,
        published_at=advisory.published,
        modified_at=advisory.modified,
        fixed_versions=list(fixed[:3]),
        locations=locations,
        run_id=run.run_id,
        created_at=run.now,
    )
    if run.dry_run:
        return row
    try:
        await row.insert()
    except DuplicateKeyError:
        return None  # another run (or replica) claimed it first: it delivers, we do not
    return row


# --- delivery ---------------------------------------------------------------------------------


async def _count_channels(project_id: str) -> int:
    channels = await WebhookChannel.find(WebhookChannel.enabled == True).to_list()  # noqa: E712
    return sum(webhook_channel_service.matches(c, "dependency.new_advisory", project_id) for c in channels)


async def _deliver_all(run: _Run) -> None:
    summary = run.summary
    for project_id, rows in run.new_rows.items():
        project = run.projects.get(project_id)
        if project is None or not rows:
            continue
        summary.alerts += len(rows)
        summary.projects_alerted += 1
        message = adv_core.build_alert(project.name, project_id, rows, run.now)
        if run.dry_run:
            card = alert_service.message_card(
                message.title, message.text, message.link, message.facts, tone="attention", eyebrow=_CARD_EYEBROW
            )
            summary.previews.append(
                {
                    "project_id": project_id,
                    "project_name": project.name,
                    "card": card,
                    "bytes": len(json.dumps(card).encode()),
                }
            )
            continue
        try:
            await _deliver(run, project, rows, message)
        except Exception:
            # WARNING, not ERROR: the ledger rows exist, so this is a delivery problem, not a lost alert
            # that a retry could fix -- and ERROR would raise a portal.error alert about alerting.
            logger.warning("live alert delivery failed", project_id=project_id, exc_info=True)


async def _deliver(run: _Run, project: Project, rows: list[LiveDependencyAlert], message) -> None:
    project_id = str(project.id)
    in_app = await notification_service.notify(
        "dependency.new_advisory",
        project_id=project_id,
        title=message.title,
        body=message.text,
        link=message.link,
        severity=message.notif_severity,
        facts=message.facts,
    )
    channels = await _count_channels(project_id)
    webhook, email = await alert_service.send_project_live_alert(
        project, message.title, message.text, message.link, message.facts
    )
    delivery = AlertDelivery(channels=channels, in_app=in_app, project_webhook=webhook, project_email=email)
    await LiveDependencyAlert.get_pymongo_collection().update_many(
        {"_id": {"$in": [r.id for r in rows]}}, {"$set": {"delivery": delivery.model_dump()}}
    )
    for row in rows:
        row.delivery = delivery
    await _audit(
        "Live Dependency Alert Raised",
        project_id,
        {
            "run_id": run.run_id,
            "count": len(rows),
            "advisories": sorted({r.advisory_id for r in rows})[:10],
            "packages": sorted({f"{r.ecosystem}:{r.package}" for r in rows})[:10],
            "channels": channels,
            "in_app": in_app,
            "project_webhook": webhook,
            "project_email": email,
        },
    )


async def _audit(action: str, project_id: str | None, metadata: dict) -> None:
    """System actor (no person did this), project-scoped when it concerns a project. Never carries a URL
    or an address."""
    try:
        await audit_service.record(
            action, actor_type="system", project_id=project_id, target_type="advisory_watch", metadata=metadata
        )
    except Exception:
        logger.warning("live alert audit failed", action=action, exc_info=True)


# --- feed health ------------------------------------------------------------------------------


async def _feed_health(run: _Run, failures: dict[str, str]) -> None:
    now, state = run.now, run.state
    total = len(adv_core.SUPPORTED_ECOSYSTEMS)
    status = "ok" if not failures else ("error" if len(failures) >= total else "partial")
    newest = max(
        (r for rows in run.new_rows.values() for r in rows), key=lambda r: r.published_at, default=None
    )
    fields: dict = {
        "last_run_finished_at": now,
        "last_status": status,
        "last_error": next(iter(failures.values()), None),
        "last_run_summary": run.summary.to_dict(),
    }
    if newest is not None:
        fields["last_advisory_id"] = newest.advisory_id
        fields["last_advisory_published_at"] = newest.published_at
    if status == "error":
        fields["consecutive_failures"] = state.consecutive_failures + 1
        fields["failing_since"] = as_utc(state.failing_since) or now
    else:
        fields.update(
            last_success_at=now, consecutive_failures=0, failing_since=None, unreachable_alerted_at=None
        )
    await _set(run.run_id, fields)

    if status != "error":
        return
    failing_since = as_utc(state.failing_since) or now
    if now - failing_since < timedelta(hours=settings.advisory_feed_unreachable_alert_hours):
        return
    # Once per outage: the atomic claim on unreachable_alerted_at, cleared by the next success.
    claimed = await _state_collection().update_one(
        {"key": STATE_KEY, "lease_owner": run.run_id, "unreachable_alerted_at": None},
        {"$set": {"unreachable_alerted_at": now}},
    )
    if claimed.matched_count == 0:
        return
    hours = int((now - failing_since).total_seconds() // 3600)
    await notification_service.notify(
        "advisories.feed_unreachable",
        title="Advisory feed unreachable",
        body=(
            f"The portal has not been able to read the OSV advisory feed for {hours}h "
            f"({fields['last_error']}). New dependency advisories are not being checked until it recovers."
        ),
        link="/admin/control-panel",
        severity="error",
    )
    await _audit(
        "Advisory Watch Failed",
        None,
        {"failing_since": failing_since.isoformat(), "consecutive_failures": fields["consecutive_failures"]},
    )


async def watch_loop() -> None:
    """Wakes every minute; run_once only does work when a run is due (the lease claim checks the
    interval). Logs at WARNING only."""
    while True:
        await asyncio.sleep(60)
        try:
            await run_once()
        except Exception:
            logger.warning("advisory watch tick failed", exc_info=True)


# --- read side --------------------------------------------------------------------------------


def to_row(doc: LiveDependencyAlert, project_name: str | None) -> LiveAlertRow:
    return LiveAlertRow(
        id=str(doc.id),
        project_id=doc.project_id,
        project_name=project_name,
        advisory_id=doc.advisory_id,
        advisory_ids=doc.advisory_ids,
        summary=doc.summary,
        ecosystem=doc.ecosystem,
        package=doc.package,
        version=doc.version,
        severity=doc.severity,
        cvss_score=doc.cvss_score,
        malicious=doc.malicious,
        published_at=as_utc(doc.published_at),
        fixed_versions=doc.fixed_versions,
        locations=[
            LiveAlertLocationOut(
                repo_label=loc.repo_label,
                manifests=loc.manifests,
                inventory_scanned_at=as_utc(loc.inventory_scanned_at),
                git_commit=loc.git_commit,
            )
            for loc in doc.locations
        ],
        created_at=as_utc(doc.created_at),
        delivery=LiveAlertDeliveryOut(**doc.delivery.model_dump()),
    )


async def status() -> LiveAlertStatus:
    ws = await workspace_settings_service.get_workspace_settings()
    state = await get_state()
    now = datetime.now(timezone.utc)
    recent = await LiveDependencyAlert.find().sort("-created_at").limit(20).to_list()
    names: dict[str, str | None] = {}
    for doc in recent:
        if doc.project_id not in names:
            project = await workspace_settings_service.load_project(doc.project_id)
            names[doc.project_id] = project.name if project else None
    ecosystems = []
    for ecosystem in adv_core.SUPPORTED_ECOSYSTEMS:
        cursor = as_utc(state.cursors.get(ecosystem))
        ecosystems.append(
            EcosystemLag(
                ecosystem=ecosystem,
                cursor=cursor,
                lag_minutes=int((now - cursor).total_seconds() // 60) if cursor else None,
            )
        )
    return LiveAlertStatus(
        enabled=ws.live_alerts_enabled,
        min_severity=ws.live_alerts_min_severity,
        include_malicious=ws.live_alerts_include_malicious,
        server_watch_enabled=settings.advisory_watch_enabled,
        interval_minutes=int(_interval().total_seconds() // 60),
        max_age_hours=settings.advisory_max_age_hours,
        last_run_started_at=as_utc(state.last_run_started_at),
        last_run_finished_at=as_utc(state.last_run_finished_at),
        last_success_at=as_utc(state.last_success_at),
        last_status=state.last_status,
        last_error=state.last_error,
        consecutive_failures=state.consecutive_failures,
        failing_since=as_utc(state.failing_since),
        last_gap_at=as_utc(state.last_gap_at),
        last_gap_hours=state.last_gap_hours,
        ecosystems=ecosystems,
        last_advisory_id=state.last_advisory_id,
        last_advisory_published_at=as_utc(state.last_advisory_published_at),
        last_run_summary=state.last_run_summary,
        coverage=InventoryCoverage(**await dependency_inventory_service.coverage()),
        email_delivery_configured=bool(settings.smtp_host),
        recent=[to_row(d, names.get(d.project_id)) for d in recent],
    )


async def project_feed(project: Project, limit: int = 50) -> ProjectLiveAlerts:
    project_id = str(project.id)
    policy = await workspace_settings_service.effective_live_alert_policy(project)
    inventories = await DependencyInventory.find(DependencyInventory.project_id == project_id).to_list()
    alerts = (
        await LiveDependencyAlert.find(LiveDependencyAlert.project_id == project_id)
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    return ProjectLiveAlerts(
        effective_min_severity=policy.min_severity,
        enabled=policy.enabled,
        inventories=[
            ProjectInventoryOut(
                repo_label=i.repo_label,
                scan_type=i.scan_type,
                scanned_at=as_utc(i.scanned_at),
                git_commit=i.git_commit,
                dep_count=i.dep_count,
                scanner_version=i.scanner_version,
                truncated=i.truncated,
            )
            for i in sorted(inventories, key=lambda i: i.repo_label)
        ],
        alerts=[to_row(a, project.name) for a in alerts],
        email_delivery_configured=bool(settings.smtp_host),
    )

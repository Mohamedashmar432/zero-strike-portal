"""Alerts about scans that failed, stalled or stopped arriving
(docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 9).

The portal can only see a pipeline that reaches it. A dead one leaves a `pending`/`running` cicd scan
(stalled) or, if it never even starts, nothing at all (silent). Everything here goes through
`notification_service.notify`, which never raises; the periodic checks additionally swallow their own
errors, because they ride on the scan queue's poll loop and must not break it.
"""

import time
from datetime import datetime, timedelta, timezone

import structlog
from pymongo import ReturnDocument

from app.core import dedupe
from app.core.config import settings
from app.core.repo_url import sanitize_repo_url
from app.models.project import Project
from app.models.scan import Scan
from app.services import notification_service

logger = structlog.get_logger(__name__)

_TICK_INTERVAL = 60.0
_last_tick: float | None = None
_SILENT_MIN_ACTIVE_DAYS = 3
_SILENT_LOOKBACK = timedelta(days=7)
_SILENT_QUIET = timedelta(hours=24)
# Only scans this recent are considered, so first boot after deploy cannot announce a backlog.
_STALLED_LOOKBACK = timedelta(days=2)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _project_name(project_id: str) -> str | None:
    if len(project_id) != 24:
        return None
    project = await Project.get(project_id)
    return project.name if project else None


def failed_facts(scan: Scan, project_name: str | None = None) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    if project_name:
        facts.append(("Project", project_name))
    facts.append(("Scan type", "Cloud" if scan.scan_type == "cloud" else "CI/CD pipeline"))
    if scan.stage:
        facts.append(("Stage", scan.stage))
    if scan.repo_url:
        facts.append(("Repository", sanitize_repo_url(scan.repo_url) or ""))
    if scan.branch:
        facts.append(("Branch", scan.branch))
    if scan.error_message:
        facts.append(("Error", scan.error_message[:500]))
    if scan.ci_build_url:
        facts.append(("CI build", scan.ci_build_url))
    return facts


async def notify_scan_failed(scan: Scan, message: str | None = None) -> None:
    """`scan.failed` with the context a person needs to act without opening the portal. Once per
    scan (a pipeline may report `failed` more than once). Never raises."""
    try:
        if not dedupe.alerts.first(f"scan.failed:{scan.id}", 86400):
            return
        await notification_service.notify(
            "scan.failed",
            project_id=scan.project_id,
            title="Scan failed",
            body=message or scan.error_message or "The scan failed.",
            link=f"/projects/{scan.project_id}/scans/{scan.id}",
            severity="error",
            facts=failed_facts(scan, await _project_name(scan.project_id)),
        )
    except Exception:
        logger.warning("scan-failed notification failed", exc_info=True)


async def check_stalled(now: datetime | None = None) -> int:
    """Alert once for each cicd scan stuck pending/running past the reap window. Returns how many."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=settings.scan_timeout_seconds * settings.queue_stuck_multiplier)
    col = Scan.get_pymongo_collection()
    candidates = await col.find(
        {
            "scan_type": "cicd",
            "status": {"$in": ["pending", "running"]},
            "updated_at": {"$lt": cutoff},
            "created_at": {"$gte": now - _STALLED_LOOKBACK},
            "stalled_alerted_at": None,
        },
        {"_id": 1},
    ).to_list(100)
    sent = 0
    for doc in candidates:
        # The claim is the dedupe: only the caller that flips the field alerts.
        raw = await col.find_one_and_update(
            {"_id": doc["_id"], "stalled_alerted_at": None},
            {"$set": {"stalled_alerted_at": now}},
            return_document=ReturnDocument.AFTER,
        )
        if raw is None:
            continue
        scan = Scan.model_validate(raw)
        name = await _project_name(scan.project_id)
        since = _utc(scan.updated_at).strftime("%Y-%m-%d %H:%M UTC")
        await notification_service.notify(
            "pipeline.upload_stalled",
            project_id=scan.project_id,
            title=f"Pipeline scan stalled{f': {name}' if name else ''}",
            body=(
                f"A CI/CD scan was created but has been {scan.status} with no update since {since}. "
                "The pipeline probably died before uploading its report."
            ),
            link=f"/projects/{scan.project_id}/scans/{scan.id}",
            severity="warning",
            facts=[*failed_facts(scan, name), ("Last activity", since)],
        )
        sent += 1
    return sent


async def check_silent(now: datetime | None = None) -> int:
    """Alert for each project whose pipeline scanned on >=3 of the last 7 days but has sent nothing
    for 24 hours. Once per project per UTC day. A pipeline that only runs on weekdays can trip this
    after a weekend; the daily dedupe keeps that to one message."""
    now = now or datetime.now(timezone.utc)
    pipeline = [
        {"$match": {"scan_type": "cicd", "created_at": {"$gte": now - _SILENT_LOOKBACK, "$lt": now}}},
        {
            "$group": {
                "_id": "$project_id",
                "days": {"$addToSet": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}}},
                "last": {"$max": "$created_at"},
            }
        },
    ]
    sent = 0
    async for row in Scan.get_pymongo_collection().aggregate(pipeline):
        last = _utc(row["last"])
        if len(row["days"]) < _SILENT_MIN_ACTIVE_DAYS or now - last < _SILENT_QUIET:
            continue
        pid = row["_id"]
        project = await Project.get(pid) if len(pid) == 24 else None
        if project is None or project.is_archived:
            continue
        if not dedupe.alerts.first(f"pipeline.silent:{pid}:{now:%Y-%m-%d}", 86400):
            continue
        stamp = f"{last:%Y-%m-%d %H:%M UTC}"
        await notification_service.notify(
            "pipeline.silent",
            project_id=pid,
            title=f"Pipeline silent: {project.name}",
            body=(
                f"{project.name} sent scans on {len(row['days'])} of the last 7 days but nothing in the "
                f"last 24 hours (last scan {stamp}). The runner, schedule or network path may be down."
            ),
            link=f"/projects/{pid}",
            severity="warning",
            facts=[("Project", project.name), ("Last scan", stamp)],
        )
        sent += 1
    return sent


async def tick() -> None:
    """Called from the scan queue's poll loop (every few seconds); does real work once a minute."""
    global _last_tick
    now = time.monotonic()
    if _last_tick is not None and now - _last_tick < _TICK_INTERVAL:
        return
    _last_tick = now
    try:
        await check_stalled()
        await check_silent()
    except Exception:
        logger.warning("pipeline alert check failed", exc_info=True)

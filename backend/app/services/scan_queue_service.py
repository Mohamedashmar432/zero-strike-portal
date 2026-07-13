"""MongoDB-backed queue for cloud scans.

Cloud scans consume backend CPU (git clone + scanner subprocess), so only a bounded
number run at once (`settings.max_concurrent_cloud_scans`). Everything past that cap
sits with status="queued" in Mongo — visible, persistent, and safe to drain from any
number of backend replicas, since the claim below is a single atomic Mongo write.

No new infra: no Redis, no RabbitMQ, no Celery — just an atomic find_one_and_update
claim plus a periodic poll loop, both running in this same FastAPI process.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from pymongo import ReturnDocument

from app.core.config import settings
from app.models.scan import Scan
from app.services import cloud_scan_service

logger = logging.getLogger(__name__)

_in_flight: set[asyncio.Task] = set()


def _log_if_failed(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("cloud scan task failed", exc_info=exc)


def _track(task: asyncio.Task) -> None:
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)
    task.add_done_callback(_log_if_failed)


async def _capacity() -> int:
    running = await Scan.find(Scan.status == "running").count()
    return max(0, settings.max_concurrent_cloud_scans - running)


async def _claim_next() -> Scan | None:
    """Atomically claim the oldest queued scan, if any. Safe across concurrent callers/replicas:
    Mongo serializes the write per-document, so only one caller's filter can still match."""
    col = Scan.get_pymongo_collection()
    raw = await col.find_one_and_update(
        {"status": "queued"},
        {
            "$set": {"status": "running", "started_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)},
            "$unset": {"repo_token": "", "repo_token_auth_scheme": ""},
        },
        sort=[("created_at", 1)],
        return_document=ReturnDocument.BEFORE,
    )
    if raw is None:
        return None
    return Scan.model_validate(raw)


async def drain_queue() -> None:
    """Claim and start as many queued cloud scans as current capacity allows."""
    capacity = await _capacity()
    for _ in range(capacity):
        scan = await _claim_next()
        if scan is None:
            break
        task = asyncio.create_task(
            cloud_scan_service.run_cloud_scan(str(scan.id), scan.repo_token, scan.repo_token_auth_scheme)
        )
        _track(task)


async def reap_stuck_scans() -> None:
    """Fail any cloud scan stuck 'running' long past a plausible crash recovery window —
    covers a backend restart mid-scan, which would otherwise leave it running forever."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.scan_timeout_seconds * settings.queue_stuck_multiplier
    )
    stuck = await Scan.find(Scan.status == "running", Scan.updated_at < cutoff).to_list()
    for scan in stuck:
        now = datetime.now(timezone.utc)
        scan.status = "failed"
        scan.error_message = "Reclaimed: worker likely crashed mid-scan"
        scan.completed_at = now
        scan.updated_at = now
        await scan.save()


async def poll_loop() -> None:
    while True:
        await asyncio.sleep(settings.queue_poll_interval_seconds)
        try:
            await reap_stuck_scans()
            await drain_queue()
        except Exception:
            logger.exception("scan queue poll tick failed")

"""MongoDB-backed queue for cloud scans.

Cloud scans consume backend CPU (git clone + scanner subprocess), so only a bounded
number run at once (`settings.max_concurrent_cloud_scans`). Everything past that cap
sits with status="queued" in Mongo — visible, persistent, and safe to drain from any
number of backend replicas, since the claim below is a single atomic Mongo write.

No new infra: no Redis, no RabbitMQ, no Celery — just an atomic find_one_and_update
claim plus a periodic poll loop, both running in this same FastAPI process.
"""

import asyncio
from datetime import timedelta

import structlog

from app.core.config import settings
from app.core.job_queue import claim_next, drain_lock, reap_stuck
from app.models.scan import Scan
from app.services import cloud_scan_service, workdir_hygiene

logger = structlog.get_logger(__name__)

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
    # Cloud scans only: the cap exists because a cloud scan runs a clone + scanner
    # subprocess *in this process*. A local/CI scan is executed on someone else's
    # machine and costs this backend nothing, so counting one against the cap let a
    # CLI run that was abandoned mid-scan (Ctrl-C, dead CI job) hold a slot until the
    # reaper got to it — with max_concurrent_cloud_scans=2, two of those stall every
    # queued cloud scan in the workspace behind a job nothing is working on.
    running = await Scan.find(Scan.status == "running", Scan.scan_type == "cloud").count()
    return max(0, settings.max_concurrent_cloud_scans - running)


async def _claim_next() -> Scan | None:
    """Atomically claim the oldest queued scan, if any. Safe across concurrent callers/replicas:
    Mongo serializes the write per-document, so only one caller's filter can still match."""
    return await claim_next(
        Scan,
        queued_status="queued",
        running_status="running",
        extra_unset={"repo_token": "", "repo_token_auth_scheme": ""},
    )


async def drain_queue() -> None:
    """Claim and start as many queued cloud scans as current capacity allows."""
    async with drain_lock("cloud_scan"):
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
    """Reclaim any cloud scan stuck 'running' long past a plausible crash recovery window —
    covers a backend restart mid-scan, which would otherwise leave it running forever.
    Cloud scans default to max_attempts=1, so this always terminally fails them today
    (see Scan.max_attempts); the requeue path exists for job kinds that opt into retries."""
    await reap_stuck(
        Scan,
        running_status="running",
        queued_status="queued",
        failed_status="failed",
        stuck_after=timedelta(seconds=settings.scan_timeout_seconds * settings.queue_stuck_multiplier),
        # "Crashed" is now a claim this can actually make: a live worker heartbeats updated_at
        # every 30s (cloud_scan_service._heartbeat), so silence past the window really does mean
        # the worker is gone -- a container restart or OOM kill -- rather than a scan that was
        # merely slow. A slow one is bounded by the scanner subprocess's own timeout instead.
        crash_message=(
            "Reclaimed: the worker running this scan stopped reporting, so it was restarted or "
            "killed mid-scan (most often the container running out of memory on a large "
            "repository)."
        ),
        dead_letter_message=(
            "Reclaimed: the worker running this scan stopped reporting; retries exhausted."
        ),
    )


def stale_workdir_age_seconds() -> int:
    """How old a clone workdir must be before the sweep may delete it: the longer of the scan and the
    remediation reap windows, i.e. past anything a live job could still be working on."""
    scan_window = settings.scan_timeout_seconds * settings.queue_stuck_multiplier
    remediation_window = settings.remediation_job_timeout_seconds * settings.remediation_queue_stuck_multiplier
    return max(scan_window, remediation_window)


async def sweep_stale_workdirs() -> int:
    """Delete clone/remediation workdirs orphaned by a hard process death (OOM kill, restart on a
    persistent volume), which skip the `finally` that normally removes them. Never raises."""
    try:
        return await asyncio.to_thread(
            workdir_hygiene.sweep_stale_workdirs, cloud_scan_service._workdir_root(), stale_workdir_age_seconds()
        )
    except Exception:
        logger.warning("stale workdir sweep failed", exc_info=True)
        return 0


async def poll_loop() -> None:
    while True:
        await asyncio.sleep(settings.queue_poll_interval_seconds)
        try:
            await reap_stuck_scans()
            await sweep_stale_workdirs()
            await drain_queue()
        except Exception:
            logger.exception("scan queue poll tick failed")

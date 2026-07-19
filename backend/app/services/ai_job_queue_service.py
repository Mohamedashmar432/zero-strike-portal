"""MongoDB-backed queue for AI analysis jobs (per-finding insight + scan-level synthesis).

Mirrors scan_queue_service.py's structure exactly: bounded concurrency
(settings.max_concurrent_ai_jobs), an atomic find_one_and_update claim (app.core.job_queue),
and a periodic poll loop for crash recovery -- no new infra, just Mongo + asyncio.
"""

import asyncio
from datetime import timedelta

import structlog

from app.core.config import settings
from app.core.job_queue import claim_next, reap_stuck
from app.models.ai_analysis_job import AIAnalysisJob
from app.services import ai_analysis_service

logger = structlog.get_logger(__name__)

_in_flight: set[asyncio.Task] = set()


def _log_if_failed(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("ai analysis job task failed", exc_info=exc)


def _track(task: asyncio.Task) -> None:
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)
    task.add_done_callback(_log_if_failed)


async def _capacity() -> int:
    running = await AIAnalysisJob.find(AIAnalysisJob.status == "running").count()
    return max(0, settings.max_concurrent_ai_jobs - running)


async def _claim_next() -> AIAnalysisJob | None:
    """Atomically claim the oldest queued AI job, if any. Safe across concurrent
    callers/replicas: Mongo serializes the write per-document."""
    return await claim_next(AIAnalysisJob, queued_status="queued", running_status="running")


async def drain_queue() -> None:
    """Claim and start as many queued AI jobs as current capacity allows."""
    capacity = await _capacity()
    for _ in range(capacity):
        job = await _claim_next()
        if job is None:
            break
        task = asyncio.create_task(ai_analysis_service.run_job(job))
        _track(task)


async def reap_stuck_ai_jobs() -> None:
    """Reclaim any AI job stuck 'running' long past a plausible crash-recovery window --
    covers a backend restart mid-job, which would otherwise leave it running forever."""
    await reap_stuck(
        AIAnalysisJob,
        running_status="running",
        queued_status="queued",
        failed_status="failed",
        stuck_after=timedelta(seconds=settings.ai_job_timeout_seconds * settings.ai_queue_stuck_multiplier),
        crash_message="Reclaimed: worker likely crashed mid-job",
        dead_letter_message="Reclaimed: worker likely crashed mid-job (retries exhausted)",
    )


async def poll_loop() -> None:
    while True:
        await asyncio.sleep(settings.queue_poll_interval_seconds)
        try:
            await reap_stuck_ai_jobs()
            await drain_queue()
        except Exception:
            logger.exception("ai job queue poll tick failed")

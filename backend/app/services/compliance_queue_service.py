"""MongoDB-backed queue for compliance audits.

The fourth peer of scan_queue_service / ai_job_queue_service / ai_remediation_queue_service,
with the same shape: bounded concurrency, an atomic find_one_and_update claim
(app.core.job_queue), and a poll loop that reaps audits stranded 'running' by a crashed or
restarted worker. No new infrastructure.
"""

import asyncio
from datetime import timedelta

import structlog

from app.core.config import settings
from app.core.job_queue import claim_next, reap_stuck
from app.models.compliance_audit import ComplianceAudit
from app.services import compliance_audit_service

logger = structlog.get_logger(__name__)

_in_flight: set[asyncio.Task] = set()


def _log_if_failed(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("compliance audit task failed", exc_info=exc)


def _track(task: asyncio.Task) -> None:
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)
    task.add_done_callback(_log_if_failed)


async def _capacity() -> int:
    running = await ComplianceAudit.find(ComplianceAudit.status == "running").count()
    return max(0, settings.max_concurrent_compliance_audits - running)


async def drain_queue() -> None:
    """Claim and start as many queued audits as current capacity allows."""
    capacity = await _capacity()
    for _ in range(capacity):
        audit = await claim_next(ComplianceAudit, queued_status="queued", running_status="running")
        if audit is None:
            break
        _track(asyncio.create_task(compliance_audit_service.run_job(audit)))


async def reap_stuck_audits() -> None:
    await reap_stuck(
        ComplianceAudit,
        running_status="running",
        queued_status="queued",
        failed_status="failed",
        stuck_after=timedelta(
            seconds=settings.compliance_audit_timeout_seconds
            * settings.compliance_queue_stuck_multiplier
        ),
        crash_message="Reclaimed: worker likely crashed mid-audit",
        dead_letter_message="Reclaimed: worker likely crashed mid-audit (retries exhausted)",
    )


async def poll_loop() -> None:
    while True:
        await asyncio.sleep(settings.queue_poll_interval_seconds)
        try:
            await reap_stuck_audits()
            await drain_queue()
        except Exception:
            logger.exception("compliance audit queue poll tick failed")

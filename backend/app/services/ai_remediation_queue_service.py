"""MongoDB-backed queue for AI Auto-Fix (remediation) jobs.

Mirrors ai_job_queue_service.py / scan_queue_service.py exactly: bounded concurrency
(settings.max_concurrent_remediation_jobs), an atomic find_one_and_update claim
(app.core.job_queue), and a periodic poll loop for crash recovery -- no new infra.

Dispatches on RemediationJob.kind: "propose" -> ai_remediation_service.run_job (read-only
agent), "apply" -> ai_remediation_apply_service.run_job (clone + validate + push + PR). The
two run services are imported lazily inside drain_queue so this module (and the model/queue
tests) import cleanly regardless of build order.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from beanie.operators import In, Or

from app.core.config import settings
from app.core.job_queue import claim_next, drain_lock, reap_stuck
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob

logger = structlog.get_logger(__name__)

_in_flight: set[asyncio.Task] = set()


def _log_if_failed(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.exception("remediation job task failed", exc_info=exc)


def _track(task: asyncio.Task) -> None:
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)
    task.add_done_callback(_log_if_failed)


async def _capacity() -> int:
    running = await RemediationJob.find(RemediationJob.status == "running").count()
    return max(0, settings.max_concurrent_remediation_jobs - running)


async def _claim_next() -> RemediationJob | None:
    """Atomically claim the oldest queued remediation job, if any. Safe across concurrent
    callers/replicas: Mongo serializes the write per-document."""
    return await claim_next(RemediationJob, queued_status="queued", running_status="running")


def _run_job(job: RemediationJob):
    # Lazy import: the propose/apply services land in later build phases and pull in the LLM
    # client, git workspace, etc. -- keep this module importable without them.
    if job.kind == "apply":
        from app.services import ai_remediation_apply_service

        return ai_remediation_apply_service.run_job(job)
    from app.services import ai_remediation_service

    return ai_remediation_service.run_job(job)


async def drain_queue() -> None:
    """Claim and start as many queued remediation jobs as current capacity allows."""
    async with drain_lock("remediation"):
        capacity = await _capacity()
        for _ in range(capacity):
            job = await _claim_next()
            if job is None:
                break
            task = asyncio.create_task(_run_job(job))
            _track(task)


async def reap_stuck_remediation_jobs() -> None:
    """Reclaim any remediation job stuck 'running' long past a plausible crash-recovery window.
    An apply job has max_attempts=1, so it dead-letters (fails) rather than retrying a write."""
    await reap_stuck(
        RemediationJob,
        running_status="running",
        queued_status="queued",
        failed_status="failed",
        stuck_after=timedelta(
            seconds=settings.remediation_job_timeout_seconds * settings.remediation_queue_stuck_multiplier
        ),
        crash_message="Reclaimed: worker likely crashed mid-job",
        dead_letter_message="Reclaimed: worker likely crashed mid-job (retries exhausted)",
    )


async def reconcile_stranded_proposals() -> None:
    """A proposal is flipped to review_state="applying" while its apply job runs. If the worker
    dies mid-apply, reap_stuck dead-letters the JOB (apply has max_attempts=1) but never touches
    the proposal -- it would sit "applying" forever, un-actionable in the UI. Mark any "applying"
    proposal whose apply job is no longer queued/running as failed so it can be dismissed/retried."""
    # "approved" and "validated" strand too (the approve route sets "approved" just before it inserts
    # the job, hence the grace window). A batch job lists its proposals in proposal_ids, so cover
    # check both fields -- matching only the lead's singular proposal_id flipped the rest mid-run.
    grace = datetime.now(timezone.utc) - timedelta(seconds=120)
    stuck = await AIFixProposal.find(
        In(AIFixProposal.review_state, ["approved", "applying", "validated"]),
        AIFixProposal.updated_at < grace,
    ).to_list()
    for proposal in stuck:
        pid = str(proposal.id)
        active = await RemediationJob.find(
            RemediationJob.kind == "apply",
            In(RemediationJob.status, ["queued", "running"]),
            Or(RemediationJob.proposal_id == pid, In(RemediationJob.proposal_ids, [pid])),
        ).first_or_none()
        if active is None:
            proposal.review_state = "failed"
            proposal.failure_reason = "The apply worker did not finish (reclaimed after a crash/restart)."
            proposal.updated_at = datetime.now(timezone.utc)
            await proposal.save()


async def poll_loop() -> None:
    while True:
        await asyncio.sleep(settings.queue_poll_interval_seconds)
        try:
            await reap_stuck_remediation_jobs()
            await reconcile_stranded_proposals()
            await drain_queue()
        except Exception:
            logger.exception("remediation job queue poll tick failed")

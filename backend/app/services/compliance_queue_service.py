"""MongoDB-backed queue for compliance audits.

The fourth peer of scan_queue_service / ai_job_queue_service / ai_remediation_queue_service,
with the same shape: bounded concurrency, an atomic find_one_and_update claim
(app.core.job_queue), and a poll loop that reaps audits stranded 'running' by a crashed or
restarted worker. No new infrastructure.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from beanie.operators import In

from app.core.compliance_catalog import SUPPORTED_FRAMEWORK_KEYS
from app.core.config import settings
from app.core.job_queue import claim_next, reap_stuck
from app.models.compliance_audit import ComplianceAudit
from app.models.project import Project
from app.models.scan import Scan
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


async def enqueue_auto_audit(scan: Scan) -> ComplianceAudit | None:
    """Queue a compliance audit for a just-completed scan, if the project opted in.

    Deterministic depth only, never `with_ai_narrative`: this fires without anyone pressing
    a button, so it must not be able to spend on LLM calls. Someone who wants narrative runs
    the audit by hand.

    Returns the queued audit, or None when the policy is off or there is nothing to audit.
    Never raises — a scan must complete even if the audit could not be queued.
    """
    from app.services import project_stats_service, workspace_settings_service

    try:
        project = await workspace_settings_service.load_project(scan.project_id)
        if project is None:
            return None
        policy = await workspace_settings_service.effective_compliance_policy(project)
        if not policy.auto_audit_on_scan:
            return None

        # An empty policy means "no default chosen", which for an unattended run is every
        # framework the evaluator will actually accept.
        frameworks = policy.frameworks or sorted(SUPPORTED_FRAMEWORK_KEYS)

        # Same guard as the manual endpoint: an audit with no scan evidence would report
        # every code-assessable control as passing off nothing at all.
        coverage = await project_stats_service.resolve_scope_coverage(
            scan.project_id, policy.audit_scope, []
        )
        if not coverage.scan_ids:
            return None

        # One audit at a time per project. Without this, a project whose repos all finish
        # scanning at once would queue an audit per repo for the same evidence set.
        active = await ComplianceAudit.find(
            ComplianceAudit.project_id == scan.project_id,
            In(ComplianceAudit.status, ["queued", "running"]),
        ).first_or_none()
        if active is not None:
            return active

        now = datetime.now(timezone.utc)
        audit = ComplianceAudit(
            project_id=scan.project_id,
            frameworks=frameworks,
            scope=policy.audit_scope,
            depth="deterministic",
            created_by=None,  # unattended
            progress_total=len(frameworks),
            created_at=now,
            updated_at=now,
        )
        await audit.insert()
        await drain_queue()
        return audit
    except Exception:
        logger.exception("auto compliance audit could not be queued", scan_id=str(scan.id))
        return None


async def reap_expired_audits() -> None:
    """Delete completed audits past their project's evidence retention window.

    Retention is per-project policy, so this groups by project rather than applying one
    global cutoff. Projects with no retention set (the default) are skipped entirely —
    `None` means keep forever, and reaping them would silently destroy evidence.
    """
    from app.services import workspace_settings_service

    ws = await workspace_settings_service.get_workspace_settings()
    projects = await Project.find_all().to_list()
    now = datetime.now(timezone.utc)
    for project in projects:
        days = (
            ws.compliance_evidence_retention_days
            if project.compliance_evidence_retention_days is None
            else project.compliance_evidence_retention_days
        )
        if not days:
            continue
        cutoff = now - timedelta(days=days)
        await ComplianceAudit.find(
            ComplianceAudit.project_id == str(project.id),
            ComplianceAudit.status == "completed",
            ComplianceAudit.created_at < cutoff,
        ).delete()


async def poll_loop() -> None:
    # Retention is checked once per this many ticks rather than every tick: it is a
    # full-collection sweep and nothing about it is time-critical to the second.
    ticks_per_reap = max(1, 3600 // max(1, settings.queue_poll_interval_seconds))
    tick = 0
    while True:
        await asyncio.sleep(settings.queue_poll_interval_seconds)
        try:
            await reap_stuck_audits()
            await drain_queue()
            tick += 1
            if tick % ticks_per_reap == 0:
                await reap_expired_audits()
        except Exception:
            logger.exception("compliance audit queue poll tick failed")

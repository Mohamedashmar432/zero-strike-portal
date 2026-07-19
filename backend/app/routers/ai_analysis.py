from datetime import datetime, timezone

from beanie.operators import In
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from app.core.deps import get_current_user
from app.core.timeutils import as_utc
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.ai_finding_insight import AIFindingInsight
from app.models.ai_scan_insight import AIScanInsight
from app.models.finding import Finding
from app.models.scan import Scan
from app.models.user import User
from app.schemas.ai_analysis import (
    AIAnalysisTriggerRequest,
    AIStatusResponse,
    FindingAnalysisResponse,
    FindingInsight,
    ScanAnalysisResponse,
    ScanInsight,
)
from app.services import ai_job_queue_service, ai_provider_config_service, audit_service, project_service, scan_service

# Status endpoint lives under /ai; the trigger/status endpoints below are identified by
# finding_id/scan_id path params, so they're a second, prefix-less router (mirrors
# routers/scans.py's own prefix-less APIRouter for the same reason). Provider CRUD lives
# in routers/ai_provider_config.py.
router = APIRouter(prefix="/ai", tags=["ai-analysis"])
finding_scan_router = APIRouter(tags=["ai-analysis"])

_JOB_STATUS_TO_API = {"queued": "queued", "running": "in_progress", "completed": "completed", "failed": "failed"}


@router.get("/status", response_model=AIStatusResponse)
async def get_ai_status(user: User = Depends(get_current_user)):
    return AIStatusResponse(enabled=await ai_provider_config_service.is_ready())


# --- Analysis trigger/status ---


def _to_finding_insight(insight: AIFindingInsight | None) -> FindingInsight | None:
    if insight is None:
        return None
    return FindingInsight(
        is_false_positive=insight.is_false_positive,
        false_positive_confidence=insight.false_positive_confidence,
        verdict_reasoning=insight.verdict_reasoning,
        improved_description=insight.improved_description,
        adjusted_severity=insight.adjusted_severity,
        severity_reasoning=insight.severity_reasoning,
        owasp=insight.owasp,
        cwe=insight.cwe,
        cvss_score=insight.cvss_score,
        explanation=insight.explanation,
        provider=insight.provider,
        model_name=insight.model_name,
        updated_at=insight.updated_at,
    )


def _to_scan_insight(insight: AIScanInsight | None) -> ScanInsight | None:
    if insight is None:
        return None
    return ScanInsight(
        summary=insight.summary,
        total_findings_analyzed=insight.total_findings_analyzed,
        false_positive_count=insight.false_positive_count,
        top_recommendations=insight.top_recommendations,
        provider=insight.provider,
        model_name=insight.model_name,
        updated_at=insight.updated_at,
    )


async def _get_finding_or_404_and_authorize(finding_id: str, user: User) -> Finding:
    finding = await Finding.get(finding_id)
    if not finding:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    await project_service.require_member(finding.project_id, user)
    return finding


async def _get_scan_or_404_and_authorize(scan_id: str, user: User) -> Scan:
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    return scan


async def _latest_job(kind: str, scope_key: str) -> AIAnalysisJob | None:
    return (
        await AIAnalysisJob.find(AIAnalysisJob.kind == kind, AIAnalysisJob.scope_key == scope_key)
        .sort("-created_at")
        .first_or_none()
    )


async def _active_job(kind: str, scope_key: str) -> AIAnalysisJob | None:
    return await AIAnalysisJob.find(
        AIAnalysisJob.kind == kind,
        AIAnalysisJob.scope_key == scope_key,
        In(AIAnalysisJob.status, ["queued", "running"]),
    ).first_or_none()


def _resolve_status(
    job: AIAnalysisJob | None, has_insight: bool
) -> tuple[str, str | None, datetime | None, int, int]:
    """A "running" regenerate still reports its last-known-good insight (fetched separately by
    the caller) rather than blanking it -- only status/error_message/started_at/progress come from
    the job. started_at + progress are only meaningful while queued/running (drive the
    "AI analyzing · N%" tag). Returns (status, error, started_at, progress_completed, progress_total)."""
    if job is not None:
        if job.status in ("queued", "running"):
            return (
                _JOB_STATUS_TO_API[job.status],
                None,
                as_utc(job.started_at or job.created_at),
                job.progress_completed,
                job.progress_total,
            )
        if job.status == "failed":
            return "failed", job.error_message, None, 0, 0
        return "completed", None, None, 0, 0  # job.status == "completed"
    return ("completed" if has_insight else "not_requested"), None, None, 0, 0


@finding_scan_router.post("/findings/{finding_id}/ai-analysis", response_model=FindingAnalysisResponse)
async def trigger_finding_analysis(
    finding_id: str,
    payload: AIAnalysisTriggerRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    finding = await _get_finding_or_404_and_authorize(finding_id, user)
    if not finding.fingerprint:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Finding has no fingerprint; cannot run AI analysis"
        )
    if not await ai_provider_config_service.is_ready():
        raise HTTPException(status.HTTP_409_CONFLICT, "AI analysis is not configured or not enabled")

    insight = await AIFindingInsight.find_one(
        AIFindingInsight.fingerprint == finding.fingerprint, AIFindingInsight.project_id == finding.project_id
    )
    if insight is not None and not payload.force:
        return FindingAnalysisResponse(status="completed", error_message=None, insight=_to_finding_insight(insight))

    active_job = await _active_job("finding", finding.fingerprint)
    if active_job is not None:
        return FindingAnalysisResponse(
            status=_JOB_STATUS_TO_API[active_job.status],
            error_message=active_job.error_message,
            insight=_to_finding_insight(insight),
        )

    now = datetime.now(timezone.utc)
    job = AIAnalysisJob(
        kind="finding",
        project_id=finding.project_id,
        scan_id=finding.scan_id,
        fingerprint=finding.fingerprint,
        scope_key=finding.fingerprint,
        force=payload.force,
        status="queued",
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await job.insert()
    background.add_task(ai_job_queue_service.drain_queue)
    await audit_service.record(
        "AI Finding Analysis Triggered",
        actor_user_id=str(user.id),
        project_id=finding.project_id,
        target_type="finding",
        target_id=str(finding.id),
        metadata={"force": payload.force},
    )
    return FindingAnalysisResponse(status="queued", error_message=None, insight=_to_finding_insight(insight))


@finding_scan_router.get("/findings/{finding_id}/ai-analysis", response_model=FindingAnalysisResponse)
async def get_finding_analysis(finding_id: str, user: User = Depends(get_current_user)):
    finding = await _get_finding_or_404_and_authorize(finding_id, user)
    insight = None
    if finding.fingerprint:
        insight = await AIFindingInsight.find_one(
            AIFindingInsight.fingerprint == finding.fingerprint, AIFindingInsight.project_id == finding.project_id
        )
    job = await _latest_job("finding", finding.fingerprint) if finding.fingerprint else None
    status_value, error_message, started_at, done, total = _resolve_status(job, insight is not None)
    return FindingAnalysisResponse(
        status=status_value,
        error_message=error_message,
        started_at=started_at,
        progress_completed=done,
        progress_total=total,
        insight=_to_finding_insight(insight),
    )


@finding_scan_router.post("/scans/{scan_id}/ai-analysis", response_model=ScanAnalysisResponse)
async def trigger_scan_analysis(
    scan_id: str,
    payload: AIAnalysisTriggerRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    scan = await _get_scan_or_404_and_authorize(scan_id, user)
    if not await ai_provider_config_service.is_ready():
        raise HTTPException(status.HTTP_409_CONFLICT, "AI analysis is not configured or not enabled")

    insight = await AIScanInsight.find_one(AIScanInsight.scan_id == scan_id)
    if insight is not None and not payload.force:
        return ScanAnalysisResponse(status="completed", error_message=None, insight=_to_scan_insight(insight))

    active_job = await _active_job("scan", scan_id)
    if active_job is not None:
        return ScanAnalysisResponse(
            status=_JOB_STATUS_TO_API[active_job.status],
            error_message=active_job.error_message,
            insight=_to_scan_insight(insight),
        )

    now = datetime.now(timezone.utc)
    job = AIAnalysisJob(
        kind="scan",
        project_id=scan.project_id,
        scan_id=scan_id,
        fingerprint=None,
        scope_key=scan_id,
        force=payload.force,
        status="queued",
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await job.insert()
    background.add_task(ai_job_queue_service.drain_queue)
    await audit_service.record(
        "AI Scan Analysis Triggered",
        actor_user_id=str(user.id),
        project_id=scan.project_id,
        target_type="scan",
        target_id=scan_id,
        metadata={"force": payload.force},
    )
    return ScanAnalysisResponse(status="queued", error_message=None, insight=_to_scan_insight(insight))


@finding_scan_router.get("/scans/{scan_id}/ai-analysis", response_model=ScanAnalysisResponse)
async def get_scan_analysis(scan_id: str, user: User = Depends(get_current_user)):
    await _get_scan_or_404_and_authorize(scan_id, user)
    insight = await AIScanInsight.find_one(AIScanInsight.scan_id == scan_id)
    job = await _latest_job("scan", scan_id)
    status_value, error_message, started_at, done, total = _resolve_status(job, insight is not None)
    return ScanAnalysisResponse(
        status=status_value,
        error_message=error_message,
        started_at=started_at,
        progress_completed=done,
        progress_total=total,
        insight=_to_scan_insight(insight),
    )

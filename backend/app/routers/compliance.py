from datetime import datetime, timezone

from beanie.operators import In
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.core.compliance_catalog import FRAMEWORK_KEYS_ORDERED, FRAMEWORKS
from app.core.deps import get_current_user
from app.core.timeutils import as_utc
from app.models.compliance_audit import ComplianceAudit
from app.models.user import User
from app.schemas.common import Page
from app.schemas.compliance import (
    ComplianceAuditCreateRequest,
    ComplianceAuditListItem,
    ComplianceAuditResponse,
    ControlSummaryOut,
    FrameworkListResponse,
    FrameworkOut,
)
from app.services import (
    ai_provider_config_service,
    audit_service,
    compliance_queue_service,
    project_service,
    project_stats_service,
)

# The catalog + audit-by-id routes are /compliance-scoped; the project-scoped routes are
# identified by a project_id path param, so they live on a second, prefix-less router --
# same split as routers/ai_analysis.py.
router = APIRouter(prefix="/compliance", tags=["compliance"])
project_router = APIRouter(tags=["compliance"])

_JOB_STATUS_TO_API = {
    "queued": "queued",
    "running": "in_progress",
    "completed": "completed",
    "failed": "failed",
}


# --- catalog ---


@router.get("/frameworks", response_model=FrameworkListResponse)
async def list_frameworks(user: User = Depends(get_current_user)):
    """The static framework/control catalog — drives the audit wizard, so it never shows a
    framework the evaluator can't actually run."""
    return FrameworkListResponse(
        items=[
            FrameworkOut(
                key=f.key,
                title=f.title,
                scope_note=f.scope_note,
                controls_total=len(f.controls),
                assessed_total=sum(1 for c in f.controls if c.selector is not None),
                controls=[
                    ControlSummaryOut(
                        id=c.id,
                        title=c.title,
                        reference=c.reference,
                        code_assessable=c.selector is not None,
                        manual_reason=c.manual_reason,
                    )
                    for c in f.controls
                ],
            )
            for f in (FRAMEWORKS[k] for k in FRAMEWORK_KEYS_ORDERED)
        ]
    )


# --- serialization ---


def _to_list_item(audit: ComplianceAudit) -> ComplianceAuditListItem:
    return ComplianceAuditListItem(
        id=str(audit.id),
        project_id=audit.project_id,
        frameworks=audit.frameworks,
        scope=audit.scope,
        depth=audit.depth,
        status=_JOB_STATUS_TO_API[audit.status],
        error_message=audit.error_message,
        started_at=as_utc(audit.started_at),
        completed_at=as_utc(audit.completed_at),
        created_at=as_utc(audit.created_at),
        progress_completed=audit.progress_completed,
        progress_total=audit.progress_total,
        findings_total=audit.findings_total,
        summaries=[s.model_dump() for s in audit.summaries],
    )


def _to_response(audit: ComplianceAudit) -> ComplianceAuditResponse:
    return ComplianceAuditResponse(
        **_to_list_item(audit).model_dump(),
        scan_ids=audit.scan_ids,
        findings_truncated=audit.findings_truncated,
        ai_note=audit.ai_note,
        controls=[c.model_dump() for c in audit.controls],
    )


async def _get_audit_or_404_and_authorize(audit_id: str, user: User) -> ComplianceAudit:
    audit = await ComplianceAudit.get(audit_id)
    if not audit:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Compliance audit not found")
    await project_service.require_member(audit.project_id, user)
    return audit


# --- audits ---


@project_router.post(
    "/projects/{project_id}/compliance-audits",
    response_model=ComplianceAuditResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_compliance_audit(
    project_id: str,
    payload: ComplianceAuditCreateRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    unknown = [k for k in payload.frameworks if k not in FRAMEWORKS]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Unknown compliance framework(s): {', '.join(unknown)}"
        )

    if payload.depth == "with_ai_narrative" and not await ai_provider_config_service.ai_ready(project_id):
        where = (
            "Project → Settings → AI Provider"
            if await ai_provider_config_service.byok_enabled()
            else "Settings → AI Provider"
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"AI explanations need a configured, active AI provider ({where}). "
            "Run the audit without them, or configure a provider first.",
        )

    # No evidence means every code-assessable control would report "pass" off nothing at all,
    # which reads as a clean bill of health the scan data does not support. Refuse instead.
    scan_ids = await project_stats_service.resolve_scope_scan_ids(
        project_id, payload.scope, payload.project_repo_ids
    )
    if not scan_ids:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No completed scans in the selected scope. Run a scan first — an audit with no scan "
            "evidence cannot say anything about these controls.",
        )

    # Application-level dedup (mongomock ignores partialFilterExpression, so a partial unique
    # index isn't an option here — same reasoning as AIAnalysisJob.Settings).
    active = await ComplianceAudit.find(
        ComplianceAudit.project_id == project_id,
        In(ComplianceAudit.status, ["queued", "running"]),
    ).first_or_none()
    if active is not None:
        return _to_response(active)

    now = datetime.now(timezone.utc)
    audit = ComplianceAudit(
        project_id=project_id,
        frameworks=payload.frameworks,
        scope=payload.scope,
        project_repo_ids=payload.project_repo_ids,
        depth=payload.depth,
        created_by=str(user.id),
        progress_total=len(payload.frameworks),
        created_at=now,
        updated_at=now,
    )
    await audit.insert()

    background.add_task(compliance_queue_service.drain_queue)
    await audit_service.record(
        "Compliance Audit Started",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="compliance_audit",
        target_id=str(audit.id),
        metadata={
            "frameworks": payload.frameworks,
            "scope": payload.scope,
            "depth": payload.depth,
            "scans": len(scan_ids),
        },
    )
    return _to_response(audit)


@project_router.get("/projects/{project_id}/compliance-audits", response_model=Page)
async def list_compliance_audits(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    query = ComplianceAudit.find(ComplianceAudit.project_id == project_id)
    total = await query.count()
    audits = (
        await query.sort(-ComplianceAudit.created_at)
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )
    return Page(
        items=[_to_list_item(a) for a in audits], total=total, page=page, page_size=page_size
    )


@router.get("/audits/{audit_id}", response_model=ComplianceAuditResponse)
async def get_compliance_audit(audit_id: str, user: User = Depends(get_current_user)):
    return _to_response(await _get_audit_or_404_and_authorize(audit_id, user))

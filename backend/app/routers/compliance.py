from datetime import datetime, timezone

from beanie.operators import In
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.core.compliance_catalog import (
    FRAMEWORK_KEYS_ORDERED,
    FRAMEWORKS,
    SUPPORTED_FRAMEWORK_KEYS,
)
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
    workspace_settings_service,
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
                        domain=c.domain,
                        description=c.description,
                        recommendation=c.recommendation,
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


def _to_response(audit: ComplianceAudit, *, reused: bool = False) -> ComplianceAuditResponse:
    return ComplianceAuditResponse(
        **_to_list_item(audit).model_dump(),
        scan_ids=audit.scan_ids,
        repos_in_scope=audit.repos_in_scope,
        repos_with_scans=audit.repos_with_scans,
        newest_scan_at=as_utc(audit.newest_scan_at),
        findings_truncated=audit.findings_truncated,
        ai_note=audit.ai_note,
        reused=reused,
        controls=[c.model_dump() for c in audit.controls],
    )


async def _identical_completed_audit(
    project_id: str,
    frameworks: list[str],
    scope: str,
    depth: str,
    project_repo_ids: list[str],
    scan_ids: list[str],
) -> ComplianceAudit | None:
    """The most recent completed audit that would produce byte-identical verdicts, if any.

    The evaluator is a pure function of (frameworks, evidence set), and the evidence set is
    fully determined by the resolved scan ids — so when those match, re-running spends an LLM
    narrative pass to reproduce a result we already have. Depth is part of the key: a
    deterministic audit is not a substitute for one with narrative, and vice versa.

    Bounded scan: only the newest few audits are candidates, since a match older than that
    means scans have moved on. Callers pass refresh=True to force a fresh run regardless.
    """
    wanted_frameworks = sorted(frameworks)
    wanted_scans = sorted(scan_ids)
    recent = (
        await ComplianceAudit.find(
            ComplianceAudit.project_id == project_id,
            ComplianceAudit.status == "completed",
        )
        .sort(-ComplianceAudit.created_at)
        .limit(10)
        .to_list()
    )
    for candidate in recent:
        if (
            sorted(candidate.frameworks) == wanted_frameworks
            and candidate.scope == scope
            and candidate.depth == depth
            and sorted(candidate.project_repo_ids) == sorted(project_repo_ids)
            and sorted(candidate.scan_ids) == wanted_scans
        ):
            return candidate
    return None


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
    project = await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    # The audit's shape comes from the project's saved compliance policy unless the caller
    # was explicit. This is the whole point of moving the wizard's questions into config:
    # one configured answer, resolved in one place, used by both the manual and the
    # automatic path.
    policy = await workspace_settings_service.effective_compliance_policy(project)
    frameworks = payload.frameworks or policy.frameworks or sorted(SUPPORTED_FRAMEWORK_KEYS)
    scope = payload.scope or policy.audit_scope
    depth = payload.depth or (
        "with_ai_narrative" if policy.audit_ai_narrative else "deterministic"
    )

    unknown = [k for k in frameworks if k not in FRAMEWORKS]
    if unknown:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Unknown compliance framework(s): {', '.join(unknown)}"
        )
    # A framework whose evidence mapping hasn't been reviewed control-by-control must not be
    # runnable, even if its catalog entry exists (see SUPPORTED_FRAMEWORK_KEYS).
    unsupported = [k for k in frameworks if k not in SUPPORTED_FRAMEWORK_KEYS]
    if unsupported:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Not available yet: {', '.join(unsupported)}. Supported frameworks: "
            f"{', '.join(FRAMEWORK_KEYS_ORDERED)}.",
        )

    if depth == "with_ai_narrative" and not await ai_provider_config_service.ai_ready(project_id):
        if payload.depth == "with_ai_narrative":
            # Explicitly asked for narrative and it cannot be produced -- say so rather than
            # silently returning something other than what was requested.
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
        # Narrative came from workspace config, not from this click. The verdicts are
        # deterministic either way, so downgrade rather than refuse the audit -- the response
        # carries the depth actually used.
        depth = "deterministic"

    # No evidence means every code-assessable control would report "pass" off nothing at all,
    # which reads as a clean bill of health the scan data does not support. Refuse instead.
    coverage = await project_stats_service.resolve_scope_coverage(
        project_id, scope, payload.project_repo_ids
    )
    scan_ids = coverage.scan_ids
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

    if not payload.refresh:
        reusable = await _identical_completed_audit(
            project_id, frameworks, scope, depth, payload.project_repo_ids, scan_ids
        )
        if reusable is not None:
            return _to_response(reusable, reused=True)

    now = datetime.now(timezone.utc)
    audit = ComplianceAudit(
        project_id=project_id,
        frameworks=frameworks,
        scope=scope,
        project_repo_ids=payload.project_repo_ids,
        depth=depth,
        created_by=str(user.id),
        progress_total=len(frameworks),
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
        # The resolved values, not the request's — an empty body is the normal case now, and
        # an audit trail saying "frameworks: []" would record nothing useful.
        metadata={
            "frameworks": frameworks,
            "scope": scope,
            "depth": depth,
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

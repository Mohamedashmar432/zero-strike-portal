"""AI Auto-Fix (remediation) HTTP surface. Trigger/poll mirror routers/ai_analysis.py (same
async-job envelope + app-level active-job dedup). Generation requires a tool-capable provider
(409 otherwise). The approve/apply write endpoint is added alongside the apply service.
"""

import difflib
import uuid
from datetime import datetime, timezone

from beanie.operators import In
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.timeutils import as_utc
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.finding import Finding
from app.models.scan import Scan
from app.models.user import User
from app.schemas.ai_remediation import (
    AIFixTriggerRequest,
    ApproveRequest,
    AutoFixInsight,
    AutoFixSummary,
    DismissRequest,
    FindingAutoFixResponse,
    FixProposalOut,
    ScanAutoFixResponse,
)
from app.services import (
    ai_remediation_queue_service,
    audit_service,
    llm_client,
    project_service,
    scan_service,
)

router = APIRouter(tags=["ai-remediation"])

_JOB_STATUS_TO_API = {"queued": "queued", "running": "in_progress", "completed": "completed", "failed": "failed"}


# --- helpers -----------------------------------------------------------------------------


async def _get_scan_or_404_and_authorize(scan_id: str, user: User) -> Scan:
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    return scan


async def _get_finding_or_404_and_authorize(finding_id: str, user: User) -> Finding:
    finding = await Finding.get(finding_id)
    if not finding:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    await project_service.require_member(finding.project_id, user)
    return finding


async def _get_proposal_or_404_and_authorize(proposal_id: str, user: User) -> AIFixProposal:
    proposal = await AIFixProposal.get(proposal_id)
    if not proposal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fix proposal not found")
    await project_service.require_member(proposal.project_id, user)
    return proposal


async def _latest_job(scope_key: str) -> RemediationJob | None:
    return (
        await RemediationJob.find(RemediationJob.scope_key == scope_key).sort("-created_at").first_or_none()
    )


async def _active_job(scope_key: str) -> RemediationJob | None:
    return await RemediationJob.find(
        RemediationJob.scope_key == scope_key, In(RemediationJob.status, ["queued", "running"])
    ).first_or_none()


def _unified_diff(original: str | None, patched: str | None, file_path: str | None) -> str | None:
    if original is None or patched is None:
        return None
    fp = file_path or "file"
    diff = difflib.unified_diff(
        original.splitlines(), patched.splitlines(), fromfile=f"a/{fp}", tofile=f"b/{fp}", lineterm=""
    )
    text = "\n".join(diff)
    return text or None


def _to_out(p: AIFixProposal, fmap: dict[str, Finding]) -> FixProposalOut:
    finding = fmap.get(p.finding_id)
    return FixProposalOut(
        id=str(p.id),
        finding_id=p.finding_id,
        scan_id=p.scan_id,
        project_id=p.project_id,
        finding_rule_name=(finding.rule_name if finding else None),
        finding_severity=(finding.severity if finding else None),
        finding_file=(finding.location.file if finding else p.file_path),
        finding_start_line=(finding.location.start_line if finding else None),
        status=p.status,
        review_state=p.review_state,
        can_fix=p.can_fix,
        confidence_score=p.confidence_score,
        original_code=p.original_code,
        patched_code=p.patched_code,
        unified_diff=_unified_diff(p.original_code, p.patched_code, p.file_path),
        explanation=p.explanation,
        patch_scope=p.patch_scope,
        file_path=p.file_path,
        risk_notes=p.risk_notes,
        manual_review_reason=p.manual_review_reason,
        branch_name=p.branch_name,
        pr_url=p.pr_url,
        pr_number=p.pr_number,
        validation=p.validation,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _summary(outs: list[FixProposalOut], total_findings: int) -> AutoFixSummary:
    s = AutoFixSummary(total_findings=total_findings)
    for o in outs:
        if o.can_fix:
            s.auto_fixable += 1
        match o.review_state:
            case "manual_review":
                s.manual_review += 1
            case "proposed":
                s.proposed += 1
            case "approved" | "applying" | "validated":
                s.approved += 1
            case "applied":
                s.applied += 1
            case "pr_open":
                s.pr_created += 1
            case "dismissed":
                s.dismissed += 1
            case "failed":
                s.failed += 1
    return s


def _resolve_status(job: RemediationJob | None, has_data: bool):
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
        return "completed", None, None, 0, 0
    return ("completed" if has_data else "not_requested"), None, None, 0, 0


async def _scan_response(scan_id: str, job: RemediationJob | None) -> ScanAutoFixResponse:
    findings = await Finding.find(Finding.scan_id == scan_id).to_list()
    fmap = {str(f.id): f for f in findings}
    proposals = await AIFixProposal.find(AIFixProposal.scan_id == scan_id).sort("-created_at").to_list()
    # One proposal per finding (the service replaces priors, but keep newest defensively).
    seen: set[str] = set()
    outs: list[FixProposalOut] = []
    for p in proposals:
        if p.finding_id in seen:
            continue
        seen.add(p.finding_id)
        outs.append(_to_out(p, fmap))
    status_value, error, started_at, done, total = _resolve_status(job, bool(outs))
    return ScanAutoFixResponse(
        status=status_value,
        error_message=error,
        started_at=started_at,
        progress_completed=done,
        progress_total=total,
        insight=AutoFixInsight(summary=_summary(outs, total_findings=len(findings)), proposals=outs),
    )


# --- scan-level trigger/poll -------------------------------------------------------------


@router.post("/scans/{scan_id}/auto-fix", response_model=ScanAutoFixResponse)
async def trigger_scan_auto_fix(
    scan_id: str,
    payload: AIFixTriggerRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    scan = await _get_scan_or_404_and_authorize(scan_id, user)
    if not await llm_client.active_provider_supports_tools():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "AI Auto-Fix needs an active, tool-capable AI provider (e.g. Anthropic or OpenAI). "
            "Configure one in Settings → AI Provider.",
        )
    scope_key = f"{scan_id}:propose"
    active = await _active_job(scope_key)
    if active is not None:
        return await _scan_response(scan_id, active)

    if payload.finding_ids:
        finding_ids = payload.finding_ids[: settings.remediation_max_findings_per_job]
    else:
        findings = (
            await Finding.find(Finding.scan_id == scan_id)
            .sort("-priority_score")
            .limit(settings.remediation_max_findings_per_job)
            .to_list()
        )
        finding_ids = [str(f.id) for f in findings]
    if not finding_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Scan has no findings to fix")

    now = datetime.now(timezone.utc)
    job = RemediationJob(
        kind="propose",
        project_id=scan.project_id,
        scan_id=scan_id,
        finding_ids=finding_ids,
        scope_key=scope_key,
        trace_id=uuid.uuid4().hex,
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await job.insert()
    background.add_task(ai_remediation_queue_service.drain_queue)
    await audit_service.record(
        "AI Fix Generation Triggered",
        actor_user_id=str(user.id),
        project_id=scan.project_id,
        target_type="scan",
        target_id=scan_id,
        metadata={"findings": len(finding_ids), "force": payload.force},
    )
    return await _scan_response(scan_id, job)


@router.get("/scans/{scan_id}/auto-fix", response_model=ScanAutoFixResponse)
async def get_scan_auto_fix(scan_id: str, user: User = Depends(get_current_user)):
    await _get_scan_or_404_and_authorize(scan_id, user)
    job = await _latest_job(f"{scan_id}:propose")
    return await _scan_response(scan_id, job)


# --- finding-level trigger/poll ----------------------------------------------------------


async def _finding_response(finding: Finding, job: RemediationJob | None) -> FindingAutoFixResponse:
    proposal = (
        await AIFixProposal.find(
            AIFixProposal.finding_id == str(finding.id), AIFixProposal.scan_id == finding.scan_id
        )
        .sort("-created_at")
        .first_or_none()
    )
    out = _to_out(proposal, {str(finding.id): finding}) if proposal else None
    status_value, error, started_at, done, total = _resolve_status(job, out is not None)
    return FindingAutoFixResponse(
        status=status_value,
        error_message=error,
        started_at=started_at,
        progress_completed=done,
        progress_total=total,
        insight=out,
    )


@router.post("/findings/{finding_id}/auto-fix", response_model=FindingAutoFixResponse)
async def trigger_finding_auto_fix(
    finding_id: str,
    payload: AIFixTriggerRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    finding = await _get_finding_or_404_and_authorize(finding_id, user)
    if not await llm_client.active_provider_supports_tools():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "AI Auto-Fix needs an active, tool-capable AI provider (e.g. Anthropic or OpenAI). "
            "Configure one in Settings → AI Provider.",
        )
    scope_key = f"{finding.scan_id}:propose:{finding_id}"
    active = await _active_job(scope_key)
    if active is not None:
        return await _finding_response(finding, active)

    now = datetime.now(timezone.utc)
    job = RemediationJob(
        kind="propose",
        project_id=finding.project_id,
        scan_id=finding.scan_id,
        finding_ids=[str(finding.id)],
        scope_key=scope_key,
        trace_id=uuid.uuid4().hex,
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await job.insert()
    background.add_task(ai_remediation_queue_service.drain_queue)
    await audit_service.record(
        "AI Fix Generation Triggered",
        actor_user_id=str(user.id),
        project_id=finding.project_id,
        target_type="finding",
        target_id=str(finding.id),
        metadata={"force": payload.force},
    )
    return await _finding_response(finding, job)


@router.get("/findings/{finding_id}/auto-fix", response_model=FindingAutoFixResponse)
async def get_finding_auto_fix(finding_id: str, user: User = Depends(get_current_user)):
    finding = await _get_finding_or_404_and_authorize(finding_id, user)
    job = await _latest_job(f"{finding.scan_id}:propose:{finding_id}")
    return await _finding_response(finding, job)


# --- proposal detail / dismiss / patch ---------------------------------------------------


@router.get("/fix-proposals/{proposal_id}", response_model=FixProposalOut)
async def get_fix_proposal(proposal_id: str, user: User = Depends(get_current_user)):
    proposal = await _get_proposal_or_404_and_authorize(proposal_id, user)
    finding = await Finding.get(proposal.finding_id)
    fmap = {proposal.finding_id: finding} if finding else {}
    return _to_out(proposal, fmap)


@router.post("/fix-proposals/{proposal_id}/dismiss", response_model=FixProposalOut)
async def dismiss_fix_proposal(
    proposal_id: str, payload: DismissRequest, user: User = Depends(get_current_user)
):
    proposal = await _get_proposal_or_404_and_authorize(proposal_id, user)
    proposal.status = "dismissed"
    proposal.review_state = "dismissed"
    if payload.reason:
        proposal.manual_review_reason = payload.reason
    proposal.updated_at = datetime.now(timezone.utc)
    await proposal.save()
    await audit_service.record(
        "AI Fix Proposal Dismissed",
        actor_user_id=str(user.id),
        project_id=proposal.project_id,
        target_type="ai_fix_proposal",
        target_id=str(proposal.id),
        metadata={"finding_id": proposal.finding_id},
    )
    finding = await Finding.get(proposal.finding_id)
    return _to_out(proposal, {proposal.finding_id: finding} if finding else {})


@router.post("/fix-proposals/{proposal_id}/approve", response_model=FixProposalOut)
async def approve_fix_proposal(
    proposal_id: str,
    payload: ApproveRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Approve a proposal and enqueue the write (branch + PR). Pushing to a customer repo is a
    privileged action -- owner/admin only, not any project member. Idempotent: a proposal already
    PR'd or with an active apply job returns as-is instead of enqueuing a second write."""
    proposal = await AIFixProposal.get(proposal_id)
    if not proposal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fix proposal not found")
    await project_service.require_owner_or_admin(proposal.project_id, user)

    if proposal.review_state == "pr_open":
        finding = await Finding.get(proposal.finding_id)
        return _to_out(proposal, {proposal.finding_id: finding} if finding else {})
    if not proposal.can_fix:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This proposal is not auto-fixable")
    if proposal.confidence_score < settings.remediation_confidence_threshold:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Confidence {proposal.confidence_score:.0f} is below the {settings.remediation_confidence_threshold:.0f} "
            "threshold required to auto-create a PR.",
        )

    scope_key = f"apply:{proposal_id}"
    if await _active_job(scope_key) is not None:
        finding = await Finding.get(proposal.finding_id)
        return _to_out(proposal, {proposal.finding_id: finding} if finding else {})

    now = datetime.now(timezone.utc)
    proposal.review_state = "approved"
    proposal.approved_by = str(user.id)
    proposal.approved_at = now
    proposal.branch_name = payload.branch_name or proposal.branch_name
    proposal.updated_at = now
    await proposal.save()

    job = RemediationJob(
        kind="apply",
        project_id=proposal.project_id,
        scan_id=proposal.scan_id,
        proposal_id=proposal_id,
        scope_key=scope_key,
        trace_id=uuid.uuid4().hex,
        max_attempts=1,  # a write must never auto-retry
        approver_user_id=str(user.id),
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await job.insert()
    background.add_task(ai_remediation_queue_service.drain_queue)
    await audit_service.record(
        "AI Fix Approved",
        actor_user_id=str(user.id),
        project_id=proposal.project_id,
        target_type="ai_fix_proposal",
        target_id=proposal_id,
        metadata={"finding_id": proposal.finding_id},
    )
    finding = await Finding.get(proposal.finding_id)
    return _to_out(proposal, {proposal.finding_id: finding} if finding else {})


@router.get("/fix-proposals/{proposal_id}/patch")
async def download_fix_patch(proposal_id: str, user: User = Depends(get_current_user)):
    proposal = await _get_proposal_or_404_and_authorize(proposal_id, user)
    diff = _unified_diff(proposal.original_code, proposal.patched_code, proposal.file_path)
    if diff is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No patch available for this proposal")
    filename = f"zerostrike-fix-{proposal_id}.patch"
    return Response(
        content=diff + "\n",
        media_type="text/x-patch",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

"""AI Auto-Fix (remediation) HTTP surface. Trigger/poll mirror routers/ai_analysis.py (same
async-job envelope + app-level active-job dedup). Generation requires a tool-capable provider
(409 otherwise). The approve/apply write endpoint is added alongside the apply service.
"""

import uuid
from datetime import datetime, timezone

from beanie.operators import In
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status

from app.core.deps import get_current_user
from app.core.timeutils import as_utc
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.audit_log import AuditLog
from app.models.finding import Finding
from app.models.finding_comment import FindingComment
from app.models.fix_conversation import ConversationMessage, FixConversation
from app.models.scan import Scan
from app.models.user import User
from app.schemas.ai_remediation import (
    ActivityEvent,
    ActivityResponse,
    AIFixTriggerRequest,
    ApproveRequest,
    AskRequest,
    AutoFixInsight,
    AutoFixSummary,
    CommentCreate,
    CommentListResponse,
    CommentOut,
    CommentSummaryResponse,
    ConversationMessageOut,
    ConversationOut,
    DismissRequest,
    FindingAutoFixResponse,
    FindingCommentCount,
    FixProposalOut,
    ProjectAutoFixListResponse,
    ProjectAutoFixScanItem,
    ProjectOverviewOut,
    ReviseRequest,
    ScanAutoFixResponse,
)
from app.services import (
    ai_remediation_queue_service,
    ai_remediation_service,
    audit_service,
    fix_pattern_service,
    llm_client,
    project_service,
    remediation_brief_service,
    remediation_project_doc_service,
    remediation_settings_service,
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


# Single implementation, shared with the brief renderer, so the diff shown in the UI, the one the
# /patch endpoint serves, and the one embedded in a brief are byte-identical.
_unified_diff = remediation_brief_service.unified_diff


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
        dependency_update=p.dependency_update,
        manual_review_reason=p.manual_review_reason,
        branch_name=p.branch_name,
        pr_url=p.pr_url,
        pr_number=p.pr_number,
        triage=p.triage,
        critique=p.critique,
        validation=p.validation,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


# Severity -> coarse risk rank. Unknown/missing severities don't raise the rating.
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
_RANK_TO_RATING = {4: "critical", 3: "high", 2: "medium", 1: "low", 0: "low"}


def _risk_rating(outs: list[FixProposalOut]) -> str:
    best = -1
    for o in outs:
        best = max(best, _SEVERITY_RANK.get((o.finding_severity or "").lower(), -1))
    return "none" if best < 0 else _RANK_TO_RATING[best]


def _summary(outs: list[FixProposalOut], total_findings: int, threshold: float) -> AutoFixSummary:
    s = AutoFixSummary(total_findings=total_findings, confidence_threshold=threshold)
    for o in outs:
        if o.can_fix:
            s.auto_fixable += 1
            if o.confidence_score >= threshold:
                s.ai_fixable += 1
            else:
                s.needs_review_on_fix += 1
        else:
            s.cannot_fix += 1
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
    s.risk_rating = _risk_rating(outs)
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
    # ponytail: one singleton read per scan (also inside the project-list loop); it's an indexed
    # find_one — thread `threshold` down if a project ever has many scans-with-fixes.
    cfg = await remediation_settings_service.get_settings()
    return ScanAutoFixResponse(
        status=status_value,
        error_message=error,
        started_at=started_at,
        progress_completed=done,
        progress_total=total,
        insight=AutoFixInsight(
            summary=_summary(outs, total_findings=len(findings), threshold=cfg.confidence_threshold),
            proposals=outs,
        ),
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
    cfg = await remediation_settings_service.get_settings()
    if not cfg.enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "AI Auto-Fix is disabled by an administrator (Settings → Auto-Fix).",
        )
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
        finding_ids = payload.finding_ids[: cfg.max_findings_per_job]
    else:
        findings = (
            await Finding.find(Finding.scan_id == scan_id)
            .sort("-priority_score")
            .limit(cfg.max_findings_per_job)
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


# --- dedicated Auto-Fix section: per-project list of scans with fixes --------------------


async def _project_list_item(scan: Scan) -> ProjectAutoFixScanItem:
    scan_id = str(scan.id)
    resp = await _scan_response(scan_id, await _latest_job(f"{scan_id}:propose"))
    return ProjectAutoFixScanItem(
        scan_id=scan_id,
        project_repo_id=scan.project_repo_id,
        repo_url=scan.repo_url,
        scan_label=scan.scan_label,
        scan_type=scan.scan_type,
        branch=scan.branch,
        scan_created_at=as_utc(scan.created_at),
        status=resp.status,
        started_at=resp.started_at,
        progress_completed=resp.progress_completed,
        progress_total=resp.progress_total,
        summary=resp.insight.summary if resp.insight else AutoFixSummary(),
    )


@router.get("/scans/{scan_id}/auto-fix/brief")
async def download_scan_brief(scan_id: str, user: User = Depends(get_current_user)):
    """The remediation brief for this scan as Markdown, rendered deterministically from MongoDB.

    Unlike /auto-fix/overview (an LLM summary of the cloned repo), this is a pure function of the
    stored documents: regenerating it costs nothing and always produces the same bytes, so it is
    rendered on request rather than cached.
    """
    await _get_scan_or_404_and_authorize(scan_id, user)
    markdown = await remediation_brief_service.render_scan_brief(scan_id)
    if markdown is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="zerostrike-remediation-{scan_id}.md"'},
    )


@router.get("/scans/{scan_id}/auto-fix/overview", response_model=ProjectOverviewOut)
async def get_scan_auto_fix_overview(scan_id: str, user: User = Depends(get_current_user)):
    """The AI-generated project remediation overview (markdown) for this scan's repo, if the propose
    agent cloned the repo and produced one. None when no clone happened (local/CI scans, private repo
    without a stored credential, etc.)."""
    scan = await _get_scan_or_404_and_authorize(scan_id, user)
    doc = await remediation_project_doc_service.latest_for_scan(
        scan.project_id, scan.project_repo_id, scan.git_commit
    )
    if doc is None:
        return ProjectOverviewOut()
    return ProjectOverviewOut(markdown=doc.markdown, generated_at=doc.generated_at, model_name=doc.model_name)


@router.get("/projects/{project_id}/auto-fix/scans", response_model=ProjectAutoFixListResponse)
async def list_project_auto_fix(project_id: str, user: User = Depends(get_current_user)):
    """Every scan in the project that has been sent to Auto-Fix (has a propose job or any
    proposal), newest first — the list that backs the dedicated Auto-Fix section."""
    await project_service.require_member(project_id, user)
    # ponytail: gather scan_ids in Python (mongomock lacks reliable .distinct); fine while the
    # number of scans-with-fixes per project is small. Add an aggregation if it grows large.
    proposals = await AIFixProposal.find(AIFixProposal.project_id == project_id).to_list()
    jobs = await RemediationJob.find(
        RemediationJob.project_id == project_id, RemediationJob.kind == "propose"
    ).to_list()
    scan_ids = {p.scan_id for p in proposals} | {j.scan_id for j in jobs}
    items: list[ProjectAutoFixScanItem] = []
    for scan_id in scan_ids:
        scan = await Scan.get(scan_id)
        if scan is not None:
            items.append(await _project_list_item(scan))
    items.sort(key=lambda i: (i.scan_created_at is not None, i.scan_created_at), reverse=True)
    return ProjectAutoFixListResponse(items=items)


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
    cfg = await remediation_settings_service.get_settings()
    if not cfg.enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "AI Auto-Fix is disabled by an administrator (Settings → Auto-Fix).",
        )
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
    # Negative signal for the fix memory. Recorded for analytics only -- dismissed patterns are
    # never read back into a prompt (see fix_pattern_service.recent_accepted).
    if proposal.can_fix:
        await fix_pattern_service.record(proposal, finding, "dismissed")
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
    # ponytail: confidence gates *auto*-approval, not a human. An owner/admin who has reviewed the
    # diff may approve a low-confidence fix; the apply job still clones, re-scans, and refuses to
    # push if the patch fails to clear the finding or introduces new >=medium findings.

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


# --- per-fix Ask-AI Q&A + "change it" revise ---------------------------------------------

_TOOL_PROVIDER_409 = (
    "AI Auto-Fix needs an active, tool-capable AI provider (e.g. Anthropic or OpenAI). "
    "Configure one in Settings → AI Provider."
)


async def _get_or_create_conversation(proposal: AIFixProposal) -> FixConversation:
    conv = await FixConversation.find_one(
        FixConversation.finding_id == proposal.finding_id,
        FixConversation.scan_id == proposal.scan_id,
    )
    if conv is None:
        conv = FixConversation(
            finding_id=proposal.finding_id, scan_id=proposal.scan_id, project_id=proposal.project_id
        )
        await conv.insert()
    return conv


def _conversation_out(proposal_id: str, conv: FixConversation) -> ConversationOut:
    return ConversationOut(
        proposal_id=proposal_id,
        messages=[
            ConversationMessageOut(
                role=m.role, body=m.body, author_user_id=m.author_user_id, kind=m.kind, created_at=m.created_at
            )
            for m in conv.messages
        ],
    )


@router.get("/fix-proposals/{proposal_id}/conversation", response_model=ConversationOut)
async def get_fix_conversation(proposal_id: str, user: User = Depends(get_current_user)):
    proposal = await _get_proposal_or_404_and_authorize(proposal_id, user)
    conv = await _get_or_create_conversation(proposal)
    return _conversation_out(proposal_id, conv)


@router.post("/fix-proposals/{proposal_id}/ask", response_model=ConversationOut)
async def ask_fix_proposal(
    proposal_id: str, payload: AskRequest, user: User = Depends(get_current_user)
):
    """Read-only Q&A about this fix. Appends the question + AI answer to the (finding-scoped)
    conversation so the whole team sees the thread. Never mutates the proposal."""
    proposal = await _get_proposal_or_404_and_authorize(proposal_id, user)
    question = payload.question.strip()
    if not question:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A question is required")

    finding = await Finding.get(proposal.finding_id)
    try:
        answer = await ai_remediation_service.ask_about_fix(proposal, finding, question)
    except llm_client.LLMNotConfiguredError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No AI provider is configured. Configure one in Settings → AI Provider.",
        )
    except llm_client.LLMTransientError:
        # Reached only after llm_client retried AND failed over across every configured provider —
        # so name that, and avoid promising a quick retry (free-tier quotas are often per-day).
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Every configured AI provider is rate-limited or unavailable right now. Free-tier "
            "quotas can be per-day — check Settings → AI Provider, or add another provider.",
        )
    except llm_client.LLMError:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "The AI provider couldn't answer right now. Try again in a moment.",
        )

    now = datetime.now(timezone.utc)
    conv = await _get_or_create_conversation(proposal)
    conv.messages.append(
        ConversationMessage(role="user", body=question, author_user_id=str(user.id), kind="qa", created_at=now)
    )
    conv.messages.append(ConversationMessage(role="assistant", body=answer, kind="qa", created_at=now))
    conv.updated_at = now
    await conv.save()
    return _conversation_out(proposal_id, conv)


@router.post("/fix-proposals/{proposal_id}/revise", response_model=FindingAutoFixResponse)
async def revise_fix_proposal(
    proposal_id: str,
    payload: ReviseRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """Re-run the fix agent for this finding with a developer instruction ("change it to X"). Enqueues
    a propose job carrying the revision note; the proposal is regenerated in place and the UI polls
    the finding-level endpoint (same envelope as Generate Fix)."""
    proposal = await _get_proposal_or_404_and_authorize(proposal_id, user)
    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "An instruction is required")
    if not await llm_client.active_provider_supports_tools():
        raise HTTPException(status.HTTP_409_CONFLICT, _TOOL_PROVIDER_409)

    finding = await Finding.get(proposal.finding_id)
    if finding is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The finding for this proposal no longer exists")

    scope_key = f"{proposal.scan_id}:propose:{proposal.finding_id}"
    active = await _active_job(scope_key)
    if active is not None:
        return await _finding_response(finding, active)

    now = datetime.now(timezone.utc)
    conv = await _get_or_create_conversation(proposal)
    conv.messages.append(
        ConversationMessage(role="user", body=instruction, author_user_id=str(user.id), kind="revision", created_at=now)
    )
    conv.updated_at = now
    await conv.save()

    job = RemediationJob(
        kind="propose",
        project_id=proposal.project_id,
        scan_id=proposal.scan_id,
        finding_ids=[proposal.finding_id],
        revision_note=instruction,
        scope_key=scope_key,
        trace_id=uuid.uuid4().hex,
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await job.insert()
    background.add_task(ai_remediation_queue_service.drain_queue)
    await audit_service.record(
        "AI Fix Revision Requested",
        actor_user_id=str(user.id),
        project_id=proposal.project_id,
        target_type="ai_fix_proposal",
        target_id=proposal_id,
        metadata={"finding_id": proposal.finding_id},
    )
    return await _finding_response(finding, job)


# --- team controls: per-finding comments + auto-fix activity timeline --------------------


async def _users_map(user_ids: set[str]) -> dict[str, User]:
    out: dict[str, User] = {}
    for uid in user_ids:
        if not uid:
            continue
        try:
            u = await User.get(uid)
        except Exception:
            u = None
        if u is not None:
            out[uid] = u
    return out


def _comment_out(c: FindingComment, umap: dict[str, User]) -> CommentOut:
    u = umap.get(c.author_user_id)
    return CommentOut(
        id=str(c.id),
        finding_id=c.finding_id,
        author_user_id=c.author_user_id,
        author_name=(u.name if u else None),
        author_email=(u.email if u else None),
        body=c.body,
        created_at=c.created_at,
    )


@router.get("/findings/{finding_id}/comments", response_model=CommentListResponse)
async def list_finding_comments(finding_id: str, user: User = Depends(get_current_user)):
    finding = await _get_finding_or_404_and_authorize(finding_id, user)
    comments = (
        await FindingComment.find(FindingComment.finding_id == str(finding.id)).sort("+created_at").to_list()
    )
    umap = await _users_map({c.author_user_id for c in comments})
    return CommentListResponse(items=[_comment_out(c, umap) for c in comments])


@router.post("/findings/{finding_id}/comments", response_model=CommentOut)
async def create_finding_comment(
    finding_id: str, payload: CommentCreate, user: User = Depends(get_current_user)
):
    finding = await _get_finding_or_404_and_authorize(finding_id, user)
    body = payload.body.strip()
    if not body:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Comment body is required")
    comment = FindingComment(
        finding_id=str(finding.id),
        scan_id=finding.scan_id,
        project_id=finding.project_id,
        author_user_id=str(user.id),
        body=body,
        created_at=datetime.now(timezone.utc),
    )
    await comment.insert()
    return _comment_out(comment, {str(user.id): user})


@router.get("/scans/{scan_id}/comments/summary", response_model=CommentSummaryResponse)
async def scan_comments_summary(scan_id: str, user: User = Depends(get_current_user)):
    """Per-finding comment counts for the scan — backs the report page's overall comments icon."""
    await _get_scan_or_404_and_authorize(scan_id, user)
    comments = await FindingComment.find(FindingComment.scan_id == scan_id).to_list()
    counts: dict[str, int] = {}
    for c in comments:
        counts[c.finding_id] = counts.get(c.finding_id, 0) + 1
    return CommentSummaryResponse(
        total=len(comments),
        by_finding=[FindingCommentCount(finding_id=fid, count=n) for fid, n in counts.items()],
    )


# Auto-fix audit actions surfaced in the team-visible activity timeline.
_ACTIVITY_ACTIONS = {
    "AI Fix Generation Triggered",
    "AI Fix Proposals Generated",
    "AI Fix Proposals Failed",
    "AI Fix Revision Requested",
    "AI Fix Approved",
    "AI Fix Proposal Dismissed",
    "AI Fix Validation Passed",
    "AI Fix Branch Pushed",
    "AI Fix PR Opened",
    "AI Fix Marked Manual Review",
    "AI Fix Failed",
}


@router.get("/scans/{scan_id}/auto-fix/activity", response_model=ActivityResponse)
async def scan_auto_fix_activity(scan_id: str, user: User = Depends(get_current_user)):
    """Team-visible timeline of every auto-fix action on this scan (proposed, approved, PR opened…)."""
    scan = await _get_scan_or_404_and_authorize(scan_id, user)
    proposals = await AIFixProposal.find(AIFixProposal.scan_id == scan_id).to_list()
    jobs = await RemediationJob.find(RemediationJob.scan_id == scan_id).to_list()
    related_ids = {str(p.id) for p in proposals} | {str(j.id) for j in jobs} | {scan_id}
    # Filter the project's recent audit trail in Python (mongomock-friendly; the set is small).
    logs = (
        await AuditLog.find(AuditLog.project_id == scan.project_id).sort("-created_at").limit(300).to_list()
    )
    events = [
        log
        for log in logs
        if log.action in _ACTIVITY_ACTIONS
        and (log.target_id in related_ids or log.metadata.get("scan_id") == scan_id)
    ]
    umap = await _users_map({e.actor_user_id for e in events if e.actor_user_id})
    return ActivityResponse(
        items=[
            ActivityEvent(
                action=e.action,
                actor_user_id=e.actor_user_id,
                actor_name=(umap[e.actor_user_id].name if e.actor_user_id in umap else None),
                target_type=e.target_type,
                target_id=e.target_id,
                metadata=e.metadata,
                created_at=e.created_at,
            )
            for e in events
        ]
    )

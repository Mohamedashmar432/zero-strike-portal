"""Request/response DTOs for AI Auto-Fix (remediation). The job envelope
(status/error_message/started_at/progress_*/insight) intentionally mirrors ai_analysis so the
frontend reuses its AiAnalysisResult<T> pattern + polling. confidence_score is 0-100."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Same lifecycle vocabulary as ai_analysis, for the same polling machinery.
RemediationStatus = Literal["not_requested", "queued", "in_progress", "completed", "failed"]

FixReviewState = Literal[
    "proposed", "approved", "applying", "validated", "pr_open", "manual_review", "dismissed", "failed"
]


class AIFixTriggerRequest(BaseModel):
    #: Redraft findings that already have a proposal. Off by default: a re-run over the same
    #: selection costs no quota (already charged) but does cost a full agent run per finding,
    #: so the default is to skip them and report the count.
    force: bool = False
    # Optional subset; when omitted a scan-level trigger proposes for all of the scan's findings.
    finding_ids: list[str] | None = None


class DismissRequest(BaseModel):
    reason: str | None = None


class ApproveRequest(BaseModel):
    # Optional override for the generated branch name.
    branch_name: str | None = None



class AskRequest(BaseModel):
    question: str


class ReviseRequest(BaseModel):
    instruction: str


class ConversationMessageOut(BaseModel):
    role: Literal["user", "assistant"]
    body: str
    author_user_id: str | None = None
    kind: Literal["qa", "revision"] = "qa"
    created_at: datetime


class ConversationOut(BaseModel):
    proposal_id: str
    messages: list["ConversationMessageOut"] = Field(default_factory=list)


class FixProposalOut(BaseModel):
    id: str
    finding_id: str
    scan_id: str
    project_id: str
    # Echoed finding context so a proposal card renders standalone.
    finding_rule_name: str | None = None
    finding_severity: str | None = None
    finding_file: str | None = None
    finding_start_line: int | None = None

    status: Literal["proposed", "applied", "dismissed"]
    review_state: FixReviewState
    can_fix: bool
    confidence_score: float  # 0-100
    original_code: str | None
    patched_code: str | None
    unified_diff: str | None = None
    explanation: str | None
    patch_scope: str | None
    file_path: str | None
    risk_notes: str | None
    dependency_update: dict | None = None
    manual_review_reason: str | None
    # Why an apply DROPPED this fix (review_state="failed"). Without it a batch's partial result is
    # unreadable in the UI: the fix left out of the PR shows "failed" and no reason.
    failure_reason: str | None = None

    branch_name: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    # Per-stage artifacts, so the UI can explain *why* a proposal is in its review_state:
    # triage (deterministic, pre-LLM), critique (post-draft review), validation (re-scan gate).
    triage: dict | None = None
    critique: dict | None = None
    validation: dict | None = None
    created_at: datetime
    updated_at: datetime


# Coarse repo-level risk read for the auto-fix report header (highest finding severity in scope).
AutoFixRiskRating = Literal["none", "low", "medium", "high", "critical"]


class AutoFixSummary(BaseModel):
    total_findings: int = 0
    #: Findings in this scan with no proposal yet. The listing is the whole scan; only
    #: execution is batched, so this is the honest "how much work is left" number and the
    #: UI labels the trigger button with it. 0 means the scan is fully covered.
    uncovered_findings: int = 0
    auto_fixable: int = 0  # can_fix (any confidence) — kept for back-compat
    manual_review: int = 0
    proposed: int = 0
    approved: int = 0
    applied: int = 0
    pr_created: int = 0
    dismissed: int = 0
    failed: int = 0
    # The 3-way breakdown the report page renders (can_fix x confidence threshold):
    ai_fixable: int = 0  # can_fix AND confidence >= remediation_confidence_threshold
    needs_review_on_fix: int = 0  # can_fix but confidence below threshold — a human should review the fix
    cannot_fix: int = 0  # can_fix == False — AI couldn't produce a safe fix, needs manual remediation
    risk_rating: AutoFixRiskRating = "none"
    # The effective threshold used for the buckets above, echoed so the UI can label them and warn on
    # a below-bar approval WITHOUT calling /remediation-settings (admin-only — a plain project owner
    # can approve a fix but cannot read that endpoint). Sending it here also means the client can
    # never disagree with the server about where the bar is.
    confidence_threshold: float = 0.0


class AutoFixInsight(BaseModel):
    summary: AutoFixSummary
    proposals: list[FixProposalOut] = Field(default_factory=list)


class ProjectAutoFixScanItem(BaseModel):
    """One row in the dedicated Auto-Fix section list (mirrors a scans-list row)."""

    scan_id: str
    project_repo_id: str | None = None
    repo_url: str | None = None
    scan_label: str | None = None
    scan_type: str | None = None
    branch: str | None = None
    scan_created_at: datetime | None = None
    status: RemediationStatus = "not_requested"
    started_at: datetime | None = None
    progress_completed: int = 0
    progress_total: int = 0
    summary: AutoFixSummary = Field(default_factory=AutoFixSummary)


class ProjectAutoFixListResponse(BaseModel):
    items: list[ProjectAutoFixScanItem] = Field(default_factory=list)


class ProjectOverviewOut(BaseModel):
    """The AI remediation project overview (markdown) for a scan's repo, if one has been generated."""

    markdown: str | None = None
    generated_at: datetime | None = None
    model_name: str | None = None


# --- team controls: per-finding comments + activity timeline -----------------------------


class CommentCreate(BaseModel):
    body: str


class CommentOut(BaseModel):
    id: str
    finding_id: str
    author_user_id: str
    author_name: str | None = None
    author_email: str | None = None
    body: str
    created_at: datetime


class CommentListResponse(BaseModel):
    items: list[CommentOut] = Field(default_factory=list)


class FindingCommentCount(BaseModel):
    finding_id: str
    count: int


class CommentSummaryResponse(BaseModel):
    total: int = 0
    by_finding: list[FindingCommentCount] = Field(default_factory=list)


class ActivityEvent(BaseModel):
    action: str
    actor_user_id: str | None = None
    actor_name: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class ActivityResponse(BaseModel):
    items: list[ActivityEvent] = Field(default_factory=list)


class ScanAutoFixResponse(BaseModel):
    status: RemediationStatus
    error_message: str | None = None
    started_at: datetime | None = None
    progress_completed: int = 0
    progress_total: int = 0
    #: Findings the per-scan allowance trimmed off this run. >0 means the user asked for more
    #: than the quota permitted and the UI must say so rather than let it pass unremarked.
    quota_skipped: int = 0
    #: Findings skipped because they already had a proposal (no LLM call spent). Re-trigger
    #: with force=true to redraft them.
    skipped_existing: int = 0
    insight: AutoFixInsight | None = None


class FindingAutoFixResponse(BaseModel):
    status: RemediationStatus
    error_message: str | None = None
    started_at: datetime | None = None
    progress_completed: int = 0
    progress_total: int = 0
    insight: FixProposalOut | None = None


class BatchApproveRequest(BaseModel):
    """Approve several proposals from ONE scan as a single apply job -> one branch, one PR.
    Scan scope is what makes the batch safe: same repo, same base branch, by construction."""

    proposal_ids: list[str] = Field(min_length=1)
    branch_name: str | None = None


class BatchApproveResponse(BaseModel):
    # What was actually queued vs. left out, so the UI states the trim instead of silently
    # dropping proposals the reviewer ticked.
    job_id: str | None = None
    approved: list[FixProposalOut]
    skipped: list["BatchSkipped"] = Field(default_factory=list)


class BatchSkipped(BaseModel):
    proposal_id: str
    reason: str

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
    force: bool = False
    # Optional subset; when omitted a scan-level trigger proposes for all of the scan's findings.
    finding_ids: list[str] | None = None


class DismissRequest(BaseModel):
    reason: str | None = None


class ApproveRequest(BaseModel):
    # Optional override for the generated branch name.
    branch_name: str | None = None


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
    manual_review_reason: str | None

    branch_name: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    validation: dict | None = None
    created_at: datetime
    updated_at: datetime


class AutoFixSummary(BaseModel):
    total_findings: int = 0
    auto_fixable: int = 0
    manual_review: int = 0
    proposed: int = 0
    approved: int = 0
    applied: int = 0
    pr_created: int = 0
    dismissed: int = 0
    failed: int = 0


class AutoFixInsight(BaseModel):
    summary: AutoFixSummary
    proposals: list[FixProposalOut] = Field(default_factory=list)


class ScanAutoFixResponse(BaseModel):
    status: RemediationStatus
    error_message: str | None = None
    started_at: datetime | None = None
    progress_completed: int = 0
    progress_total: int = 0
    insight: AutoFixInsight | None = None


class FindingAutoFixResponse(BaseModel):
    status: RemediationStatus
    error_message: str | None = None
    started_at: datetime | None = None
    progress_completed: int = 0
    progress_total: int = 0
    insight: FixProposalOut | None = None

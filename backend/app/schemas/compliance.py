from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.compliance_audit import AuditDepth, AuditScope, ControlStatus

# Same vocabulary as AI analysis so the frontend reuses one polling envelope/hook: the DB's
# "running" is surfaced as "in_progress" (see routers/compliance.py _JOB_STATUS_TO_API).
ComplianceAuditStatus = Literal["queued", "in_progress", "completed", "failed"]


# --- catalog (static; drives the wizard) ---


class ControlSummaryOut(BaseModel):
    id: str
    title: str
    reference: str
    code_assessable: bool
    manual_reason: str | None = None


class FrameworkOut(BaseModel):
    key: str
    title: str
    scope_note: str
    controls_total: int
    assessed_total: int  # how many of those a code scanner can speak to
    controls: list[ControlSummaryOut] = Field(default_factory=list)


class FrameworkListResponse(BaseModel):
    items: list[FrameworkOut]


# --- audit run ---


class ComplianceAuditCreateRequest(BaseModel):
    frameworks: list[str] = Field(min_length=1)
    scope: AuditScope = "latest"
    project_repo_ids: list[str] = Field(default_factory=list)  # empty = every repo
    depth: AuditDepth = "deterministic"


class ControlEvidenceOut(BaseModel):
    fingerprint: str
    scan_id: str
    rule_id: str | None = None
    severity: str | None = None
    file: str
    line: int | None = None
    message: str


class ControlResultOut(BaseModel):
    framework: str
    control_id: str
    control_title: str
    control_reference: str
    status: ControlStatus
    rationale: str
    ai_explanation: str | None = None
    ai_remediation: str | None = None
    evidence: list[ControlEvidenceOut] = Field(default_factory=list)
    evidence_total: int = 0
    severity_counts: dict[str, int] = Field(default_factory=dict)


class FrameworkSummaryOut(BaseModel):
    framework: str
    framework_title: str
    scope_note: str
    controls_total: int
    assessed_total: int
    passed: int
    failed: int
    partial: int
    not_applicable: int
    needs_manual_review: int


class ComplianceAuditListItem(BaseModel):
    """The audit without its control bodies — for the project's audit history list."""

    id: str
    project_id: str
    frameworks: list[str]
    scope: AuditScope
    depth: AuditDepth
    status: ComplianceAuditStatus
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    progress_completed: int = 0
    progress_total: int = 0
    findings_total: int = 0
    summaries: list[FrameworkSummaryOut] = Field(default_factory=list)


class ComplianceAuditResponse(ComplianceAuditListItem):
    scan_ids: list[str] = Field(default_factory=list)
    findings_truncated: bool = False
    ai_note: str | None = None
    controls: list[ControlResultOut] = Field(default_factory=list)

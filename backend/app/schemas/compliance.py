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
    domain: str = "General Controls"
    description: str = ""
    recommendation: str = ""
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
    """Every field is optional: an empty body means "run the audit this project is
    configured for", which is what the Run Audit button sends.

    The three settings that used to be asked at run time by a three-step wizard --
    frameworks, evidence scope, and whether to pay for the AI narrative -- are now
    configured on the project's Compliance Config tab and resolved from
    workspace_settings_service.effective_compliance_policy. They stay accepted here so a
    CI client or a one-off run can still be explicit, but nothing has to be.
    """

    #: Empty = the configured frameworks (and, if none are configured, every supported one).
    frameworks: list[str] = Field(default_factory=list)
    #: None = the configured evidence scope.
    scope: AuditScope | None = None
    project_repo_ids: list[str] = Field(default_factory=list)  # empty = every repo
    #: None = with_ai_narrative when the workspace has authorised it, deterministic otherwise.
    depth: AuditDepth | None = None
    #: Re-run even when an identical completed audit over the same scans exists. Default False
    #: returns that audit instead, because the evaluator is deterministic — the verdicts would
    #: be byte-identical and the AI narrative would be paid for twice.
    refresh: bool = False


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
    domain: str = "General Controls"
    description: str = ""
    recommendation: str = ""
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
    #: Percentage of code-assessable controls passed — NOT a compliance percentage.
    compliance_score: int = 0
    #: assessed_total / controls_total, as a percentage: the ceiling on the score above.
    coverage_percent: int = 0


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
    #: Repo coverage of the selected scope. repos_with_scans < repos_in_scope means the audit
    #: saw only part of the project, and the UI says so.
    repos_in_scope: int = 0
    repos_with_scans: int = 0
    newest_scan_at: datetime | None = None
    findings_truncated: bool = False
    ai_note: str | None = None
    #: True when the trigger returned an existing identical audit instead of re-running one.
    #: Not persisted — set by the router on that response only.
    reused: bool = False
    controls: list[ControlResultOut] = Field(default_factory=list)

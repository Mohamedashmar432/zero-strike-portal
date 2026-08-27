"""One project-level compliance audit: both the durable job (claimed by app.core.job_queue,
same as AIAnalysisJob and RemediationJob) and its result, in a single document.

Results are embedded rather than split into per-control documents because they are written
once and always read as a unit -- there is no query that wants one control across audits.
Embedding avoids a second collection, a second index set, a join on every read, and a second
cascade-delete. Document size is bounded by settings.compliance_max_evidence_per_control.

Evidence references findings by `fingerprint`, never by `_id`: report ingestion is
delete-then-insert (report_ingestion_service.ingest), so a rescan changes every finding's
ObjectId while the fingerprint survives.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel

ComplianceAuditStatus = Literal["queued", "running", "completed", "failed"]
AuditScope = Literal["latest", "history"]
AuditDepth = Literal["deterministic", "with_ai_narrative"]

# `not_applicable` is part of the contract but is never emitted in v1: the honest use would
# be "the scanner never analysed this class of artifact", and zero SCA findings is
# indistinguishable from "this repo has no manifests". Scoping questions (is this system in
# HIPAA scope? does it process special-category data?) are human judgement and land in
# needs_manual_review instead. Reserved so adding it later isn't a breaking API change.
ControlStatus = Literal["pass", "fail", "partial", "not_applicable", "needs_manual_review"]


class ControlEvidence(BaseModel):
    fingerprint: str
    scan_id: str
    rule_id: str | None = None
    severity: str | None = None
    file: str
    line: int | None = None
    message: str


class ControlResult(BaseModel):
    framework: str
    control_id: str
    control_title: str
    control_reference: str
    status: ControlStatus
    domain: str = "General Controls"
    description: str = ""
    recommendation: str = ""
    rationale: str  # deterministic, template-generated -- never LLM-written
    ai_explanation: str | None = None
    ai_remediation: str | None = None
    evidence: list[ControlEvidence] = Field(default_factory=list)  # capped
    evidence_total: int = 0  # exact match count; may exceed len(evidence)
    severity_counts: dict[str, int] = Field(default_factory=dict)


class FrameworkSummary(BaseModel):
    framework: str
    framework_title: str
    scope_note: str
    controls_total: int
    assessed_total: int  # controls a code scanner can speak to at all
    passed: int = 0
    failed: int = 0
    partial: int = 0
    not_applicable: int = 0
    needs_manual_review: int = 0
    # Percentage of *code-assessable* controls that passed (0-100). Deliberately not a
    # compliance percentage: manual-only controls are not in the denominator, so this number
    # cannot be read as "we are N% compliant". `coverage_percent` is what makes that visible.
    compliance_score: int = 0
    # assessed_total / controls_total, as a percentage. How much of the framework this tool
    # can speak to at all — the honest ceiling on the score above.
    coverage_percent: int = 0


class ComplianceAudit(Document):
    project_id: str
    frameworks: list[str]
    scope: AuditScope
    project_repo_ids: list[str] = Field(default_factory=list)  # empty = every repo
    depth: AuditDepth
    status: ComplianceAuditStatus = "queued"
    retry_count: int = 0
    max_attempts: int = 2
    created_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    # Progress is counted in frameworks, not findings: the deterministic pass is effectively
    # instant and only the optional per-framework LLM call takes real time.
    progress_completed: int = 0
    progress_total: int = 0
    # The exact scans the evidence set was drawn from -- so a result stays interpretable
    # after later scans land.
    scan_ids: list[str] = Field(default_factory=list)
    # Scan coverage of the selected scope, recorded so a reader can tell an audit that saw
    # every repo from one that saw two of nine. An audit is only as complete as its scans.
    repos_in_scope: int = 0
    repos_with_scans: int = 0
    newest_scan_at: datetime | None = None
    findings_total: int = 0
    findings_truncated: bool = False
    ai_note: str | None = None  # why the AI narrative is missing, when it is
    summaries: list[FrameworkSummary] = Field(default_factory=list)
    controls: list[ControlResult] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "compliance_audits"
        indexes = [
            IndexModel([("status", 1), ("created_at", 1)]),  # job_queue.claim_next
            IndexModel([("project_id", 1), ("created_at", -1)]),  # project audit list
        ]

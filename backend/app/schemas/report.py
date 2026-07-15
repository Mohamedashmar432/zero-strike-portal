"""Pydantic models for parsing the Go scanner's report JSON.

The scanner (github.com/Mohamedashmar432/zero-strike-SAST-engine, internal/report + internal/core) marshals
its structs with no JSON tags, so keys are the Go field names verbatim (PascalCase,
acronyms preserved: ID, RuleID, CWE, OWASP, DetectorID, AdvisoryIDs, ...). These models
mirror that shape via explicit aliases and are mapped to the snake_case Beanie
Finding/Report documents by report_ingestion_service. populate_by_name lets tests build
fixtures with the snake_case field names too; extra="ignore" drops GroupBy and any
fields a future scanner build adds.

Go marshals a nil slice/map as JSON `null` (not `[]`/`{}`), so every collection field
coerces null -> empty via a BeforeValidator; Pydantic's default_factory only fires when
the key is absent, not when it is present-but-null.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.models.finding import (
    ConfigEmbedded,
    DependencyEmbedded,
    EvidenceEmbedded,
    LocationEmbedded,
    SecretEmbedded,
    TaintContextEmbedded,
)
from app.models.report import DiagnosticEmbedded, ScanStatsEmbedded

_go = ConfigDict(populate_by_name=True, extra="ignore")


def _nz_list(v):
    return [] if v is None else v


def _nz_dict(v):
    return {} if v is None else v


StrList = Annotated[list[str], BeforeValidator(_nz_list)]
StrDict = Annotated[dict[str, str], BeforeValidator(_nz_dict)]
IntDict = Annotated[dict[str, int], BeforeValidator(_nz_dict)]


class GoLocationIn(BaseModel):
    model_config = _go
    file: str = Field("", alias="File")
    start_line: int | None = Field(None, alias="StartLine")
    end_line: int | None = Field(None, alias="EndLine")
    start_col: int | None = Field(None, alias="StartCol")
    end_col: int | None = Field(None, alias="EndCol")


class GoEvidenceIn(BaseModel):
    model_config = _go
    snippet: str | None = Field(None, alias="Snippet")
    start_line: int | None = Field(None, alias="StartLine")
    end_line: int | None = Field(None, alias="EndLine")


class GoSecretIn(BaseModel):
    model_config = _go
    detector_id: str | None = Field(None, alias="DetectorID")
    entropy: float | None = Field(None, alias="Entropy")
    redacted: str | None = Field(None, alias="Redacted")


class GoDependencyIn(BaseModel):
    model_config = _go
    ecosystem: str | None = Field(None, alias="Ecosystem")
    package: str | None = Field(None, alias="Package")
    installed_version: str | None = Field(None, alias="InstalledVersion")
    vulnerable_range: str | None = Field(None, alias="VulnerableRange")
    fixed_version: str | None = Field(None, alias="FixedVersion")
    advisory_ids: StrList = Field(default_factory=list, alias="AdvisoryIDs")
    manifest: str | None = Field(None, alias="Manifest")
    direct: bool | None = Field(None, alias="Direct")


class GoConfigIn(BaseModel):
    model_config = _go
    framework: str | None = Field(None, alias="Framework")
    config_file: str | None = Field(None, alias="ConfigFile")
    key: str | None = Field(None, alias="Key")


class GoTaintContextIn(BaseModel):
    model_config = _go
    source_var: str | None = Field(None, alias="SourceVar")
    source_expr: str | None = Field(None, alias="SourceExpr")
    sink: str | None = Field(None, alias="Sink")
    path: Annotated[list[GoLocationIn], BeforeValidator(_nz_list)] = Field(
        default_factory=list, alias="Path"
    )


class GoFindingIn(BaseModel):
    model_config = _go
    finding_id: str | None = Field(None, alias="ID")
    rule_id: str | None = Field(None, alias="RuleID")
    rule_name: str | None = Field(None, alias="RuleName")
    category: str | None = Field(None, alias="Category")
    severity: str | None = Field(None, alias="Severity")
    confidence: str | None = Field(None, alias="Confidence")
    message: str | None = Field(None, alias="Message")
    location: GoLocationIn = Field(default_factory=GoLocationIn, alias="Location")
    language: str | None = Field(None, alias="Language")
    evidence: Annotated[list[GoEvidenceIn], BeforeValidator(_nz_list)] = Field(
        default_factory=list, alias="Evidence"
    )
    cwe: StrList = Field(default_factory=list, alias="CWE")
    owasp: StrList = Field(default_factory=list, alias="OWASP")
    references: StrList = Field(default_factory=list, alias="References")
    metadata: StrDict = Field(default_factory=dict, alias="Metadata")
    fingerprint: str | None = Field(None, alias="Fingerprint")
    kind: str | None = Field(None, alias="Kind")
    secret: GoSecretIn | None = Field(None, alias="Secret")
    dependency: GoDependencyIn | None = Field(None, alias="Dependency")
    config: GoConfigIn | None = Field(None, alias="Config")
    rationale: str | None = Field(None, alias="Rationale")
    remediation: str | None = Field(None, alias="Remediation")
    taint_context: GoTaintContextIn | None = Field(None, alias="TaintContext")


class GoStatsIn(BaseModel):
    model_config = _go
    files_scanned: int | None = Field(None, alias="FilesScanned")
    files_skipped: int | None = Field(None, alias="FilesSkipped")
    files_cached: int | None = Field(None, alias="FilesCached")
    total_findings: int | None = Field(None, alias="TotalFindings")
    suppressed: int | None = Field(None, alias="Suppressed")
    by_severity: IntDict = Field(default_factory=dict, alias="BySeverity")
    by_language: IntDict = Field(default_factory=dict, alias="ByLanguage")
    by_category: IntDict = Field(default_factory=dict, alias="ByCategory")
    by_kind: IntDict = Field(default_factory=dict, alias="ByKind")
    # ByScanner is intentionally not modeled — it duplicates ByKind and is dropped on ingest.


class GoDiagnosticIn(BaseModel):
    model_config = _go
    severity: str | None = Field(None, alias="Severity")
    message: str | None = Field(None, alias="Message")
    location: GoLocationIn | None = Field(None, alias="Location")


class GoReportIn(BaseModel):
    model_config = _go
    scanner_scan_id: str | None = Field(None, alias="ScanID")
    scanner_version: str | None = Field(None, alias="ScannerVersion")
    started_at: datetime | None = Field(None, alias="StartedAt")
    duration_ns: int | None = Field(None, alias="Duration")
    root_path: str | None = Field(None, alias="RootPath")
    git_commit: str | None = Field(None, alias="GitCommit")
    branch: str | None = Field(None, alias="Branch")
    hostname: str | None = Field(None, alias="Hostname")
    findings: Annotated[list[GoFindingIn], BeforeValidator(_nz_list)] = Field(
        default_factory=list, alias="Findings"
    )
    stats: GoStatsIn = Field(default_factory=GoStatsIn, alias="Stats")
    diagnostics: Annotated[list[GoDiagnosticIn], BeforeValidator(_nz_list)] = Field(
        default_factory=list, alias="Diagnostics"
    )


# --- API response models (portal -> frontend) ---


class FindingResponse(BaseModel):
    id: str
    scan_id: str
    project_id: str
    project_repo_id: str | None
    finding_id: str | None
    fingerprint: str | None
    rule_id: str | None
    rule_name: str | None
    category: str | None
    severity: str | None
    confidence: str | None
    priority_score: float | None
    priority_tier: str | None
    message: str
    location: LocationEmbedded
    language: str | None
    evidence: list[EvidenceEmbedded]
    cwe: list[str]
    owasp: list[str]
    references: list[str]
    metadata: dict[str, str]
    kind: str | None
    secret: SecretEmbedded | None
    dependency: DependencyEmbedded | None
    config: ConfigEmbedded | None
    rationale: str | None
    remediation: str | None
    taint_context: TaintContextEmbedded | None
    created_at: datetime


class ReportResponse(BaseModel):
    scan_id: str
    project_id: str
    scanner_scan_id: str | None
    scanner_version: str | None
    started_at: datetime | None
    duration_ms: int | None
    root_path: str | None
    git_commit: str | None
    branch: str | None
    hostname: str | None
    stats: ScanStatsEmbedded
    diagnostics: list[DiagnosticEmbedded]
    html_available: bool
    generated_at: datetime

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel


class LocationEmbedded(BaseModel):
    file: str
    start_line: int | None = None
    end_line: int | None = None
    start_col: int | None = None
    end_col: int | None = None


class EvidenceEmbedded(BaseModel):
    snippet: str | None = None
    start_line: int | None = None
    end_line: int | None = None


class SecretEmbedded(BaseModel):
    detector_id: str | None = None
    entropy: float | None = None
    redacted: str | None = None


class DependencyEmbedded(BaseModel):
    ecosystem: str | None = None
    package: str | None = None
    installed_version: str | None = None
    vulnerable_range: str | None = None
    fixed_version: str | None = None
    advisory_ids: list[str] = []
    manifest: str | None = None
    direct: bool | None = None


class ConfigEmbedded(BaseModel):
    framework: str | None = None
    config_file: str | None = None
    key: str | None = None


class TaintContextEmbedded(BaseModel):
    source_var: str | None = None
    source_expr: str | None = None
    sink: str | None = None
    path: list[LocationEmbedded] = []


class Finding(Document):
    scan_id: str
    project_id: str
    # Denormalized from the owning Scan at ingestion time (see report_ingestion_service) so
    # per-repo aggregations (risk-repo-count, OWASP-by-repo) never need to join `scans`.
    # None for findings ingested before this field existed.
    project_repo_id: str | None = None
    finding_id: str | None = None
    fingerprint: str | None = None
    rule_id: str | None = None
    rule_name: str | None = None
    category: str | None = None
    severity: Literal["critical", "high", "medium", "low", "info"] | None = None
    confidence: str | None = None
    # Computed at ingestion time from severity + OWASP relevance + confidence — see
    # app.core.priority.compute_priority. None for findings ingested before this field
    # existed; self-heals on the next (re-)scan since ingestion always replaces findings.
    priority_score: float | None = None
    priority_tier: Literal["critical", "high", "medium", "low"] | None = None
    message: str
    location: LocationEmbedded
    language: str | None = None
    evidence: list[EvidenceEmbedded] = []
    cwe: list[str] = []
    owasp: list[str] = []
    references: list[str] = []
    metadata: dict[str, str] = Field(default_factory=dict)
    kind: Literal["sast", "secret", "sca", "config"] | None = None
    secret: SecretEmbedded | None = None
    dependency: DependencyEmbedded | None = None
    config: ConfigEmbedded | None = None
    rationale: str | None = None
    remediation: str | None = None
    taint_context: TaintContextEmbedded | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "findings"
        indexes = [
            IndexModel([("scan_id", 1), ("priority_score", -1)]),
            IndexModel([("project_id", 1), ("severity", 1), ("created_at", -1)]),
            IndexModel([("project_id", 1), ("project_repo_id", 1), ("severity", 1)]),
            IndexModel([("fingerprint", 1), ("project_id", 1)]),
            IndexModel([("rule_id", 1)]),
            IndexModel([("language", 1)]),
            IndexModel([("kind", 1)]),
        ]

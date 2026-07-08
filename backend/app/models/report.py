from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel


class ScanStatsEmbedded(BaseModel):
    files_scanned: int | None = None
    files_skipped: int | None = None
    files_cached: int | None = None
    total_findings: int | None = None
    suppressed: int | None = None
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_language: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    by_kind: dict[str, int] = Field(default_factory=dict)


class DiagnosticEmbedded(BaseModel):
    severity: str | None = None
    message: str | None = None
    location: str | None = None


class Report(Document):
    scan_id: str
    project_id: str
    scanner_scan_id: str | None = None
    scanner_version: str | None = None
    started_at: datetime | None = None
    duration_ms: int | None = None
    root_path: str | None = None
    git_commit: str | None = None
    branch: str | None = None
    hostname: str | None = None
    stats: ScanStatsEmbedded = Field(default_factory=ScanStatsEmbedded)
    diagnostics: list[DiagnosticEmbedded] = []
    json_path: str
    html_path: str | None = None
    json_uploaded_at: datetime
    html_uploaded_at: datetime | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "reports"
        indexes = [
            IndexModel([("scan_id", 1)], unique=True),
            IndexModel([("project_id", 1)]),
        ]

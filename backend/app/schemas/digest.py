from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DigestSettingsRequest(BaseModel):
    """PUT body. The `last_*` fields of the response are not accepted back (ignored if sent)."""

    enabled: bool = False
    frequency: Literal["daily", "weekly"] = "daily"
    hour_utc: int = Field(3, ge=0, le=23)
    minute_utc: int = Field(30, ge=0, le=59)
    weekday: int = Field(0, ge=0, le=6)  # 0 = Monday; weekly only
    project_ids: list[str] = Field(default_factory=list)  # empty = every project
    include_stale_projects: bool = True


class DigestSettingsResponse(DigestSettingsRequest):
    last_sent_at: datetime | None = None
    last_status: Literal["sent", "error"] | None = None
    last_error: str | None = None


class DigestRow(BaseModel):
    project_id: str
    name: str
    pipeline_runs: int = 0
    pipeline_failed: int = 0
    cloud_scans: int = 0
    cloud_failed: int = 0
    critical: int = 0
    high: int = 0
    # Over every repo of the project: resolved is all-time, new_findings were first seen in the period.
    resolved: int = 0
    new_findings: int = 0
    # False-positive rate inputs: resolved as a false positive or admin-accepted as one, over all of them.
    false_positives: int = 0
    vulnerabilities: int = 0


class DigestTotals(BaseModel):
    pipeline_runs: int = 0
    pipeline_failed: int = 0
    cloud_scans: int = 0
    cloud_failed: int = 0
    critical: int = 0
    high: int = 0


class OutdatedPipeline(BaseModel):
    """CI/CD scans in the period that ran a scanner other than the newest published binary, grouped by
    (project, repository + runner host, version)."""

    project_id: str
    project: str
    repository: str
    scanner_version: str
    runs: int
    last_run_at: datetime | None = None


class ScannerHealth(BaseModel):
    engine_available: bool
    backend_scanner_version: str
    latest_binary_version: str | None
    projects_outdated: int = 0  # distinct projects in outdated_pipelines
    outdated_pipelines: list[OutdatedPipeline] = Field(default_factory=list)  # oldest version first
    # Advisory ids first reported by any project's dependency findings in the period (a count, no list).
    new_advisory_count: int = 0


class StaleProject(BaseModel):
    project_id: str
    name: str
    last_scan_at: datetime | None


class QuotaWarning(BaseModel):
    project_id: str
    name: str
    used: int
    limit: int


class DigestPreview(BaseModel):
    period_start: datetime
    period_end: datetime
    rows: list[DigestRow]
    totals: DigestTotals
    scanner: ScannerHealth
    stale_projects: list[StaleProject]
    quota_warnings: list[QuotaWarning]


class DigestSendError(BaseModel):
    channel_id: str
    name: str
    error: str


class DigestSendResponse(BaseModel):
    sent: int
    errors: list[DigestSendError]
    cards: int = 0  # cards posted to each channel (scanner, project status, summary; or one per project)

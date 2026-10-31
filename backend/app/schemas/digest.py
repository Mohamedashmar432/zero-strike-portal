from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.project_insights import NewCves


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
    quota_used: int = 0
    quota_limit: int = 0
    new_cves: NewCves = Field(default_factory=NewCves)


class DigestTotals(BaseModel):
    pipeline_runs: int = 0
    pipeline_failed: int = 0
    cloud_scans: int = 0
    cloud_failed: int = 0
    critical: int = 0
    high: int = 0
    quota_used: int = 0
    quota_limit: int = 0
    new_cves: NewCves = Field(default_factory=NewCves)


class NewAdvisory(BaseModel):
    """An advisory id first reported by at least one project in the period (OSV lookup at scan time)."""

    id: str
    severity: str
    projects: int


class ScannerHealth(BaseModel):
    engine_available: bool
    backend_scanner_version: str
    latest_binary_version: str | None
    outdated_ci_runners: int
    rule_pack_version: int | None
    # Custom rules in the active rule pack. The built-in SAST rules are the scanner's own and the
    # portal does not hold a count of them.
    rule_count: int
    osv_reachable: bool
    # Round-trip of each OSV.dev endpoint the scanner calls at scan time (querybatch, vulns/{id}); None =
    # unreachable or 5xx. The scanner keeps no local CVE database, so this is the whole "feed" status.
    osv_batch_ms: int | None = None
    osv_vuln_ms: int | None = None
    osv_checked_at: datetime | None = None
    last_dependency_scan_at: datetime | None = None
    new_cve_ids: list[str] = Field(default_factory=list)  # at most 5
    new_advisories: list[NewAdvisory] = Field(default_factory=list)  # at most 8, worst first
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
    cards: int = 0  # cards posted to each channel (scanner health, project status, summary)

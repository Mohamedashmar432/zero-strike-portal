from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.scan import ScanStatus, ScanType
from app.schemas.dashboard import SeverityCounts


class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_archived: bool | None = None
    # "inherit" clears the override (stored as None); None here means "not provided in
    # this patch", distinguishing "don't touch" from "explicitly clear."
    report_template: Literal["inherit", "standard", "executive"] | None = None


class ScanStatusCounts(BaseModel):
    pending: int = 0
    queued: int = 0
    running: int = 0
    completed: int = 0
    failed: int = 0


class ProjectStatsItem(BaseModel):
    project_id: str
    total_findings: int
    findings_by_severity: SeverityCounts
    scan_status_counts: ScanStatusCounts
    risk_repo_count: int
    total_repo_count: int


class ProjectStatsResponse(BaseModel):
    items: dict[str, ProjectStatsItem]


class ScanHistoryItem(BaseModel):
    scan_id: str
    status: ScanStatus
    created_at: datetime
    completed_at: datetime | None
    total_findings: int
    findings_by_severity: SeverityCounts
    # Optional context for the History timeline — populated by scan-activity, left None by the
    # older per-repo scan-history endpoint.
    scan_type: ScanType | None = None
    scanned_by: str | None = None


class OwaspSummaryResponse(BaseModel):
    project_id: str
    project_repo_id: str | None
    by_owasp: dict[str, int]


class RepoScanGroup(BaseModel):
    repo_id: str | None  # None for the synthetic "Unlinked scans" group
    repo_label: str
    provider: str | None
    scans: list[ScanHistoryItem]  # newest -> oldest


class ProjectScanActivityResponse(BaseModel):
    repos: list[RepoScanGroup]
    # Live posture: sum of each repo's most recent COMPLETED scan, NOT the all-time total.
    current_findings: SeverityCounts
    current_findings_total: int


class ProjectAiUsageResponse(BaseModel):
    enabled: bool
    active_provider: str | None
    active_model: str | None
    total_requests: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str
    is_archived: bool
    scan_count: int
    last_scan_at: datetime | None
    report_template: Literal["standard", "executive"] | None
    created_at: datetime
    updated_at: datetime
    my_role: Literal["owner", "collaborator", "admin"]
    # Populated only on GET /projects/{id} (via project_stats_service) — None on the list/
    # create/update responses, which don't attach per-project aggregates to avoid N+1
    # queries; the projects list page uses the batched GET /projects/stats instead.
    total_findings: int | None = None
    findings_by_severity: SeverityCounts | None = None
    scan_status_counts: ScanStatusCounts | None = None
    risk_repo_count: int | None = None
    total_repo_count: int | None = None

from datetime import datetime

from pydantic import BaseModel, Field

from app.models.scan import ScanStatus, ScanType
from app.schemas.project import CloudScanQuota


class ScanCounts(BaseModel):
    total: int = 0
    completed: int = 0
    failed: int = 0
    # cloud: queued + running; cicd: pending + running
    active: int = 0


class InsightsTotals(BaseModel):
    projects: int
    projects_created: int
    repos: int
    cloud: ScanCounts
    cicd: ScanCounts


class LastError(BaseModel):
    scan_id: str
    scan_type: ScanType
    message: str
    at: datetime


class UsersBlock(BaseModel):
    total: int
    registered_in_window: int
    registered_today: int
    active_in_window: int
    active_today: int
    never_signed_in: int
    pending_approval: int
    disabled: int


class CveRef(BaseModel):
    id: str
    severity: str


class NewCves(BaseModel):
    count: int = 0
    latest: list[CveRef] = Field(default_factory=list)  # newest first, at most 2


class ProjectInsightsRow(BaseModel):
    project_id: str
    name: str
    is_archived: bool
    created_at: datetime
    repos: int
    cloud: ScanCounts
    cicd: ScanCounts
    last_scan_at: datetime | None
    last_error: LastError | None
    cloud_scan_quota: CloudScanQuota
    members: int = 0
    active_users: int = 0
    new_cves: NewCves = Field(default_factory=NewCves)


class ProjectInsightsResponse(BaseModel):
    since: datetime
    until: datetime
    totals: InsightsTotals
    users: UsersBlock
    projects: list[ProjectInsightsRow]


class ScanRequestItem(BaseModel):
    scan_id: str
    project_id: str
    project_name: str | None  # None: the project has been deleted
    scan_type: ScanType
    triggered_by: str
    status: ScanStatus
    stage: str | None
    repo_url: str | None
    branch: str | None
    scan_label: str | None
    ci_provider: str | None
    ci_build_url: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    quota_exempt: bool


class ScanRequestsResponse(BaseModel):
    total: int
    items: list[ScanRequestItem]


class CloudScanLimitRequest(BaseModel):
    # None resets the project to the portal default; 0 pauses cloud scanning for it.
    monthly_limit: int | None = Field(None, ge=0, le=10000)


class ActiveUser(BaseModel):
    user_id: str
    email: str
    name: str
    days_active: int
    last_seen_at: datetime


class TimelineEvent(BaseModel):
    at: datetime
    action: str
    actor_type: str
    actor_email: str | None
    target_type: str | None
    target_id: str | None
    metadata: dict


class ProjectActivityResponse(BaseModel):
    project_id: str
    name: str
    active_users: list[ActiveUser]
    timeline: list[TimelineEvent]

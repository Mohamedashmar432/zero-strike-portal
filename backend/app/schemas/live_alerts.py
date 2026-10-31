from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Deliberately no `direct` anywhere in these responses: the scanner's Direct flag is unreliable in every
# ecosystem, so it is stored as raw data and never shown.

LiveAlertMinSeverity = Literal["critical", "high", "medium"]


class LiveAlertLocationOut(BaseModel):
    repo_label: str
    manifests: list[str]
    inventory_scanned_at: datetime | None
    git_commit: str | None


class LiveAlertDeliveryOut(BaseModel):
    channels: int  # webhook channels the event matched
    in_app: int  # in-app notifications written
    project_webhook: Literal["sent", "failed", "off"]
    project_email: Literal["sent", "failed", "not_configured", "off"]


class LiveAlertRow(BaseModel):
    id: str
    project_id: str
    project_name: str | None  # None when the project no longer exists
    advisory_id: str
    advisory_ids: list[str]
    summary: str
    ecosystem: str
    package: str
    version: str
    severity: Literal["critical", "high", "medium", "low"]
    cvss_score: float | None
    malicious: bool
    published_at: datetime
    fixed_versions: list[str]
    locations: list[LiveAlertLocationOut]
    created_at: datetime
    delivery: LiveAlertDeliveryOut


class EcosystemLag(BaseModel):
    ecosystem: str
    cursor: datetime | None  # None until the first run has recorded the feed head
    lag_minutes: int | None


class InventoryCoverage(BaseModel):
    projects_active: int
    projects_with_inventory: int
    inventories_cloud: int
    inventories_cicd: int
    oldest_inventory_at: datetime | None


class LiveAlertStatus(BaseModel):
    enabled: bool  # the workspace switch
    min_severity: LiveAlertMinSeverity
    include_malicious: bool
    server_watch_enabled: bool  # True = ADVISORY_WATCH_ENABLED=true in the environment (the watcher may run)
    interval_minutes: int
    max_age_hours: int
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_success_at: datetime | None
    last_status: Literal["ok", "partial", "error"] | None
    last_error: str | None
    consecutive_failures: int
    failing_since: datetime | None
    last_gap_at: datetime | None
    last_gap_hours: float | None
    ecosystems: list[EcosystemLag]
    last_advisory_id: str | None
    last_advisory_published_at: datetime | None
    last_run_summary: dict
    coverage: InventoryCoverage
    email_delivery_configured: bool
    recent: list[LiveAlertRow]


class LiveAlertSettingsUpdate(BaseModel):
    enabled: bool | None = None
    min_severity: LiveAlertMinSeverity | None = None
    include_malicious: bool | None = None


class RunPreview(BaseModel):
    project_id: str
    project_name: str
    card: dict  # the Adaptive Card exactly as it would be posted
    bytes: int


class LiveAlertRunResponse(BaseModel):
    status: Literal["ran", "busy", "skipped"]
    dry_run: bool
    summary: dict
    previews: list[RunPreview] = Field(default_factory=list)


class ProjectInventoryOut(BaseModel):
    repo_label: str
    scan_type: str
    scanned_at: datetime
    git_commit: str | None
    dep_count: int
    scanner_version: str | None
    truncated: bool


class ProjectLiveAlerts(BaseModel):
    effective_min_severity: Literal["critical", "high", "medium", "off"]
    enabled: bool
    inventories: list[ProjectInventoryOut]
    alerts: list[LiveAlertRow]
    email_delivery_configured: bool

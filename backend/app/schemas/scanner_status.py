from datetime import datetime

from pydantic import BaseModel

from app.models.scan import ScanStage


class BinaryChecklistItem(BaseModel):
    os: str
    arch: str
    published: bool
    version: str | None = None
    uploaded_at: datetime | None = None
    uploaded_by: str | None = None
    uploaded_by_email: str | None = None


class RunningScanItem(BaseModel):
    scan_id: str
    project_id: str
    started_at: datetime | None
    stuck: bool
    # Which phase of the pipeline the scan is in. The reason the queue view can now say what a
    # stuck job was actually doing instead of only that it stopped moving.
    stage: ScanStage | None = None
    stage_started_at: datetime | None = None


class QueueStatus(BaseModel):
    running: int
    queued: int
    max_concurrent: int
    running_scans: list[RunningScanItem]


class FailureItem(BaseModel):
    scan_id: str
    project_id: str
    scan_type: str
    error_message: str | None
    completed_at: datetime | None


class CloneWorkspaceStatus(BaseModel):
    """Live clone/remediation workdirs on this replica. A count above the running scans, or a size
    that never falls back, is a leak showing up before it becomes an outage."""

    workdir_count: int
    total_mb: int
    free_mb: int
    min_free_mb: int
    max_repo_mb: int


class ScannerStatusResponse(BaseModel):
    engine_available: bool
    binaries: list[BinaryChecklistItem]
    queue: QueueStatus
    recent_failures: list[FailureItem]
    clones: CloneWorkspaceStatus

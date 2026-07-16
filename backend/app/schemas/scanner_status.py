from datetime import datetime

from pydantic import BaseModel


class BinaryChecklistItem(BaseModel):
    os: str
    arch: str
    published: bool
    version: str | None = None
    uploaded_at: datetime | None = None
    uploaded_by: str | None = None


class RunningScanItem(BaseModel):
    scan_id: str
    project_id: str
    started_at: datetime | None
    stuck: bool


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


class ScannerStatusResponse(BaseModel):
    engine_available: bool
    binaries: list[BinaryChecklistItem]
    queue: QueueStatus
    recent_failures: list[FailureItem]

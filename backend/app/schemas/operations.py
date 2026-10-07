from datetime import datetime
from typing import Literal

from pydantic import BaseModel

QueueKind = Literal["cloud_scan", "ai_analysis", "remediation", "compliance"]


class QueueJob(BaseModel):
    kind: QueueKind
    job_id: str
    project_id: str
    project_name: str | None = None
    # What the UI already holds for this job: the scan id (scans, AI analysis, auto-fix) or the
    # audit id (compliance) — so a page can find "its" job without knowing the job's own id.
    ref_id: str
    status: Literal["queued", "running", "failed"]
    summary: str
    stage: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    # Queued only: 1-based place in this queue, and when it is expected to start.
    position: int | None = None
    estimated_start_at: datetime | None = None
    # Failed only.
    error_message: str | None = None
    completed_at: datetime | None = None


class QueueSummary(BaseModel):
    kind: QueueKind
    label: str
    capacity: int
    running: int
    queued: int
    avg_duration_seconds: float
    # True while there are fewer than ~3 finished jobs to average — the ETA is a fixed guess then.
    avg_is_default: bool
    oldest_queued_at: datetime | None = None


class QueueResponse(BaseModel):
    server_time: datetime
    queues: list[QueueSummary]
    jobs: list[QueueJob]


class SystemLoad(BaseModel):
    source: Literal["cgroup", "host"]
    cpu_percent: float
    cpu_cores: float
    memory_used_bytes: int
    memory_limit_bytes: int
    memory_percent: float | None
    process_rss_bytes: int
    subprocess_count: int
    subprocess_rss_bytes: int
    disk_used_bytes: int | None
    disk_total_bytes: int | None


class OperationsResponse(QueueResponse):
    system: SystemLoad
    recent_failures: list[QueueJob]

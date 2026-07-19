from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class SeverityCounts(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class RecentScanItem(BaseModel):
    scan_id: str
    project_id: str
    project_name: str
    status: Literal["pending", "queued", "running", "completed", "failed"]
    scan_type: Literal["local", "cloud", "cicd"]
    created_at: datetime
    findings_by_severity: SeverityCounts
    ai_analysis_status: Literal["queued", "in_progress", "completed", "failed"] | None = None
    ai_analysis_started_at: datetime | None = None
    ai_analysis_progress_completed: int = 0
    ai_analysis_progress_total: int = 0


class DashboardStatsResponse(BaseModel):
    project_count: int
    scan_count: int
    findings_by_severity: SeverityCounts
    recent_scans: list[RecentScanItem]

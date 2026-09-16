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


class PostureCoverageOut(BaseModel):
    """How much of the workspace the exposure number actually saw.

    Exposure without coverage reads as complete when it isn't: a workspace where half the repos
    were never scanned would otherwise look half as risky as it is.
    """

    repos_scanned: int = 0
    repos_without_completed_scan: int = 0
    has_unlinked_scans: bool = False


class DashboardStatsResponse(BaseModel):
    project_count: int
    # Historical volume — every scan ever run. Deliberately NOT the same thing as the severity
    # counts below, which are current exposure only.
    scan_count: int
    # Current exposure: the newest completed scan per repo scope, never the sum of every scan
    # ever ingested (findings persist per scan, so summing counts a rescanned repo twice).
    findings_by_severity: SeverityCounts
    posture_coverage: PostureCoverageOut = PostureCoverageOut()
    recent_scans: list[RecentScanItem]

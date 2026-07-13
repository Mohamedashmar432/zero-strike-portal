from pydantic import BaseModel


class SeverityCounts(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class DashboardStatsResponse(BaseModel):
    project_count: int
    scan_count: int
    findings_by_severity: SeverityCounts

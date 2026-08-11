"""Response DTOs for the AI usage dashboard. Identical shape at both scopes (a project's own
calls, and portal-wide) -- `by_project` is simply empty in project scope, which is what lets one
frontend component render both."""

from datetime import datetime

from pydantic import BaseModel


class AiUsageTotals(BaseModel):
    requests: int
    failed: int
    success_rate: float  # percent, 0-100
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    avg_duration_ms: int


class AiUsageDayPoint(BaseModel):
    date: str  # YYYY-MM-DD, UTC
    requests: int
    failed: int
    success_rate: float
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class AiUsageFeatureRow(AiUsageTotals):
    feature: str


class AiUsageModelRow(AiUsageTotals):
    provider: str
    model_name: str | None


class AiUsageProjectRow(AiUsageTotals):
    project_id: str | None
    project_name: str


class AiAnalyticsResponse(BaseModel):
    days: int
    totals: AiUsageTotals
    timeseries: list[AiUsageDayPoint]
    by_feature: list[AiUsageFeatureRow]
    by_model: list[AiUsageModelRow]
    by_project: list[AiUsageProjectRow]  # portal scope only; empty for a single project


class AiUsageEventRow(BaseModel):
    id: str
    created_at: datetime
    project_id: str | None
    project_name: str | None
    scan_id: str | None
    scope: str
    feature: str
    provider: str
    model_name: str | None
    status: str
    error_type: str | None
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class AiUsageEventPage(BaseModel):
    items: list[AiUsageEventRow]
    total: int
    page: int
    page_size: int

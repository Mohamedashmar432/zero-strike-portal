from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# --- Status (derived from whichever AIProviderConfig, if any, is active) ---


class AIStatusResponse(BaseModel):
    enabled: bool


# --- Analysis trigger/status (per-finding insight + scan-level synthesis) ---

AIAnalysisStatus = Literal["not_requested", "queued", "in_progress", "completed", "failed"]


class AIAnalysisTriggerRequest(BaseModel):
    force: bool = False


class FindingInsight(BaseModel):
    """AIFindingInsight's enrichment fields, verbatim."""

    is_false_positive: bool | None
    false_positive_confidence: float | None
    # The AI's confidence in its own verdict (0-1) — what the UI shows as "AI confidence".
    analysis_confidence: float | None = None
    verdict_reasoning: str | None
    improved_description: str | None
    # How many other findings share this rule (same vuln recurring across the repo).
    similar_finding_count: int = 0
    # Display-only AI severity overlay (None when the AI didn't override the scanner severity).
    adjusted_severity: Literal["critical", "high", "medium", "low", "info"] | None = None
    severity_reasoning: str | None = None
    owasp: list[str] = Field(default_factory=list)
    cwe: list[str] = Field(default_factory=list)
    cvss_score: float | None
    explanation: str | None
    provider: str | None
    model_name: str | None
    updated_at: datetime


class ScanInsight(BaseModel):
    """AIScanInsight's fields, verbatim."""

    summary: str | None
    total_findings_intended: int = 0
    total_findings_analyzed: int
    false_positive_count: int
    top_recommendations: list[str] = Field(default_factory=list)
    provider: str | None
    model_name: str | None
    updated_at: datetime


class FindingAnalysisResponse(BaseModel):
    status: AIAnalysisStatus
    error_message: str | None
    # While queued/running: when it started + batch progress, for the "AI analyzing · N%" tag.
    started_at: datetime | None = None
    progress_completed: int = 0
    progress_total: int = 0
    insight: FindingInsight | None


class ScanAnalysisResponse(BaseModel):
    status: AIAnalysisStatus
    error_message: str | None
    started_at: datetime | None = None
    progress_completed: int = 0
    progress_total: int = 0
    insight: ScanInsight | None

"""AI-generated whole-report synthesis (see docs/ARCHITECTURE_REVIEW_AND_AI_ROADMAP.md).

One document per scan, produced by reducing that scan's already-computed
AIFindingInsight documents into a single narrative -- not a second full analysis pass.

Schema only for now -- no service writes to this collection yet (AI Analysis is a
later phase).
"""

from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class AIScanInsight(Document):
    scan_id: str
    project_id: str

    summary: str | None = None
    total_findings_analyzed: int = 0
    false_positive_count: int = 0
    top_recommendations: list[str] = Field(default_factory=list)

    provider: str | None = None
    model_name: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_scan_insights"
        indexes = [
            IndexModel([("scan_id", 1)], unique=True),
            IndexModel([("project_id", 1)]),
        ]

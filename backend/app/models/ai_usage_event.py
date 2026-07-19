"""One row per LLM call, attributed to a project (and scan when known).

The global running totals on AIProviderConfig can't be sliced per project -- this
collection captures the same usage numbers keyed by project_id so per-project token/cost
aggregation is a simple $group. Written alongside (not instead of) the provider $inc.
"""

from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class AIUsageEvent(Document):
    project_id: str
    scan_id: str | None = None
    provider: str
    model_name: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_usage_events"
        indexes = [
            IndexModel([("project_id", 1)]),
        ]

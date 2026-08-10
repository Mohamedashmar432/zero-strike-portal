"""One row per LLM call -- the portal's AI call log.

The global running totals on AIProviderConfig can't be sliced per project, per feature or per
day, and they say nothing about *why* a call failed. This collection captures the same usage
numbers plus enough context to answer "where did the spend go" and "why is AI broken for this
project", at both scopes: a project's own calls, and portal-wide across every project.

Metadata only, deliberately: prompts and responses carry customer source code, findings and
secrets, and must never land in a queryable collection. See ai_provider_config_service.record_usage
(the only writer) and ai_analytics_service (the only reader).
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

# ponytail: fixed 180-day retention via a TTL index rather than a settings knob and a reaper task.
# The collection is unbounded (one row per LLM call) and prod runs on an Atlas M0 with a 512MB cap.
# Lifetime totals survive on AIProviderConfig regardless, so expiring rows only costs old detail.
# Make it configurable if someone actually asks for longer history.
_RETENTION_SECONDS = 180 * 24 * 60 * 60


class AIUsageEvent(Document):
    # None only for a call with no project attribution (an admin-triggered one). Under BYOK such a
    # call has no key it is entitled to use and never reaches a provider, so in practice these are
    # portal-scope rows from the shared-provider mode.
    project_id: str | None = None
    scan_id: str | None = None
    config_id: str | None = None
    scope: Literal["project", "portal"] = "portal"
    provider: str
    model_name: str | None = None
    # Which AI feature spent this. The breakdown that makes the dashboard actionable -- without it
    # "$40 of Anthropic" is a number nobody can act on. Set by each llm_client caller.
    feature: str = "unknown"
    status: Literal["success", "failed"] = "success"
    # Exception class name (LLMPermanentError, LLMTransientError, ...) -- never the raw provider
    # message, which can echo back prompt content.
    error_type: str | None = None
    duration_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_usage_events"
        indexes = [
            # Compound, ordered to serve both the per-project dashboard (equality on project_id,
            # range + sort on created_at) and its paginated log from one index.
            IndexModel([("project_id", 1), ("created_at", -1)]),
            # Portal-wide dashboard: no project_id predicate, just the time window.
            IndexModel([("created_at", -1)]),
            IndexModel([("created_at", 1)], expireAfterSeconds=_RETENTION_SECONDS),
        ]

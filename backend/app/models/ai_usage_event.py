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

# Closed vocabulary for AIUsageEvent.error_code. Defined here (with the model, not with the
# classifier) because it is the stored contract: the analytics reader groups by it and the UI
# labels it, so adding a value is a schema change, not an implementation detail.
LLMErrorCode = Literal[
    "context_length_exceeded",
    "rate_limited",
    "auth_failed",
    "model_not_found",
    "permission_denied",
    "bad_request",
    "timeout",
    "connection_error",
    "provider_unavailable",
    "malformed_response",
    "not_configured",
    "unknown",
]

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
    # WHY it failed, from a closed vocabulary (see llm_client.classify_error). error_type alone
    # collapses "your key is wrong", "that model does not exist" and "the prompt exceeds this
    # model's window" into one string -- LLMPermanentError -- and those need three different
    # actions from the user. Deliberately a code and not the provider's message: the no-raw-text
    # rule in this module's docstring is what keeps prompt content out of a queryable collection,
    # and a classified code carries the actionable part without it.
    error_code: LLMErrorCode | None = None
    # Which failover attempt this row is (1-based) and, past the first, the provider it fell back
    # from. Without these a 3-provider failover writes three rows that read as three unrelated
    # outages instead of one chain that ended in a success.
    attempt: int = 1
    failover_from: str | None = None
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
            # Failure-reason breakdown on the analytics pages: status equality + time range,
            # grouped by error_code. Sparse-ish in practice (most rows are successes).
            IndexModel([("status", 1), ("created_at", -1)]),
        ]

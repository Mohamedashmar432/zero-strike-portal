"""Admin-configured AI provider configurations for AI Analysis.

Multiple providers can be stored side by side (unlike WorkspaceSettings' true
singleton) so an admin can pre-configure several and switch between them without
re-entering credentials. At most one document has `is_active=True` at any time --
that single flag is what AI Analysis actually uses (see ai_provider_config_service.
get_active_config); none active means AI analysis is off, mirroring the old
`enabled=False` singleton state this replaces.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

# Matches litellm model-string prefixes used by the sibling zero-strike-cli project
# this mirrors (see SecurityAgentRunner._PROVIDER_MODEL_MAP / SecurityAnalyzer).
AIProvider = Literal[
    "anthropic", "openai", "lmstudio", "kimi", "nvidia_nim", "openrouter", "custom", "commandcode", "groq"
]

# Self-hosted OpenAI-compatible servers -- the admin points these at their own instance
# (no fixed public endpoint), and that instance typically enforces no auth at all (e.g. LM
# Studio). Every other provider is a hosted SaaS API that always needs a real key.
NO_KEY_REQUIRED_PROVIDERS: frozenset[str] = frozenset({"lmstudio", "custom"})


class AIProviderConfig(Document):
    name: str = "Legacy Provider"  # lets a pre-migration singleton doc load without a migration script
    provider: AIProvider = "anthropic"
    model_name: str | None = None
    # Encrypted at rest via app.core.security.encrypt_secret/decrypt_secret — never store
    # or return the raw key (see ai_provider_config_service, routers/ai_provider_config.py).
    api_key_encrypted: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    # Exactly one document has is_active=True at a time (or none = AI analysis off). This
    # replaces the old boolean `enabled` field -- there is no separate "enabled" concept
    # anymore, only "the active provider" (or lack thereof).
    is_active: bool = False

    # Running usage/cost totals, updated atomically by ai_provider_config_service.record_usage
    # after every completed llm_client call attributed to this provider.
    total_requests: int = 0
    total_failed_requests: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cost_usd: float = 0.0
    last_used_at: datetime | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: str | None = None

    class Settings:
        name = "ai_provider_config"
        indexes = [IndexModel([("is_active", 1)])]

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.timeutils import as_utc
from app.models.ai_provider_config import AIProvider
from app.services import ai_provider_config_service


class AIProviderConfigCreateRequest(BaseModel):
    name: str
    provider: AIProvider
    model_name: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    api_key: str | None = None
    # USD per 1M tokens; overrides litellm's price map for this config. Omitted/null = use the map.
    input_cost_per_million: float | None = Field(None, ge=0)
    output_cost_per_million: float | None = Field(None, ge=0)


class AIProviderConfigUpdateRequest(BaseModel):
    name: str
    provider: AIProvider
    model_name: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    # Omitted (None) = keep the existing encrypted key unchanged; clear_api_key=True explicitly wipes it.
    api_key: str | None = None
    clear_api_key: bool = False
    # USD per 1M tokens; overrides litellm's price map for this config. Omitted/null = use the map.
    input_cost_per_million: float | None = Field(None, ge=0)
    output_cost_per_million: float | None = Field(None, ge=0)


class AIProviderConfigResponse(BaseModel):
    id: str
    name: str
    project_id: str | None  # None = portal-wide (admin-managed); set = that project's own key
    provider: AIProvider
    model_name: str | None
    base_url: str | None
    temperature: float
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    is_active: bool
    has_api_key: bool  # never the encrypted or raw key itself
    # Where the key lives. Read-only; the secret NAME is safe to show, the value never is.
    key_storage: Literal["key_vault", "encrypted_database", "none"]
    key_vault_secret_name: str | None
    total_requests: int
    total_failed_requests: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime
    updated_by: str | None

    @classmethod
    def from_config(cls, config) -> "AIProviderConfigResponse":
        """The one place an AIProviderConfig becomes a response. Both the admin router and the
        per-project BYOK routes go through it, so the has_api_key-instead-of-the-key rule and the
        UTC normalization can't drift apart between them."""
        if config.api_key_secret_name:
            key_storage = "key_vault"
        elif config.api_key_encrypted:
            key_storage = "encrypted_database"
        else:
            key_storage = "none"
        return cls(
            id=str(config.id),
            name=config.name,
            project_id=config.project_id,
            provider=config.provider,
            model_name=config.model_name,
            base_url=config.base_url,
            temperature=config.temperature,
            input_cost_per_million=config.input_cost_per_million,
            output_cost_per_million=config.output_cost_per_million,
            is_active=config.is_active,
            has_api_key=ai_provider_config_service.has_api_key(config),
            key_storage=key_storage,
            key_vault_secret_name=config.api_key_secret_name or None,
            total_requests=config.total_requests,
            total_failed_requests=config.total_failed_requests,
            total_prompt_tokens=config.total_prompt_tokens,
            total_completion_tokens=config.total_completion_tokens,
            total_cost_usd=config.total_cost_usd,
            last_used_at=as_utc(config.last_used_at),
            created_at=as_utc(config.created_at),
            updated_at=as_utc(config.updated_at),
            updated_by=config.updated_by,
        )


class AIProviderTestRequest(BaseModel):
    provider: AIProvider
    model_name: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0


class AIProviderTestResponse(BaseModel):
    success: Literal[True] = True
    message: str


class AISettingsResponse(BaseModel):
    project_byok_enabled: bool


class AISettingsUpdateRequest(BaseModel):
    project_byok_enabled: bool


# --- AI budgets and pricing (docs/AI_PRICING_AND_BUDGETS.md) -------------------------------------


class AIBudgetUpdateRequest(BaseModel):
    # null = no limit on that metric.
    usd_monthly: float | None = Field(None, gt=0)
    tokens_monthly: int | None = Field(None, gt=0)
    alert_percent: int = Field(80, ge=1, le=99)
    hard_stop: bool = False


class AIBudgetResponse(AIBudgetUpdateRequest):
    # Month-to-date usage (UTC calendar month), so the page can show progress next to the limits.
    period_start: datetime
    used_usd: float
    used_tokens: int
    requests: int
    # Calls nothing could price: their cost is missing from used_usd, not zero.
    unpriced_requests: int


class AIPricingStatusResponse(BaseModel):
    models: int
    source: str | None  # "remote" (live list) or "local" (the copy bundled with litellm)
    url: str
    refreshed_at: datetime | None
    fallback_reason: str | None

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.core.timeutils import as_utc
from app.models.ai_provider_config import AIProvider


class AIProviderConfigCreateRequest(BaseModel):
    name: str
    provider: AIProvider
    model_name: str | None = None
    base_url: str | None = None
    temperature: float = 0.0
    api_key: str | None = None


class AIProviderConfigUpdateRequest(BaseModel):
    name: str
    provider: AIProvider
    model_name: str | None = None
    base_url: str | None = None
    temperature: float | None = None
    # Omitted (None) = keep the existing encrypted key unchanged; clear_api_key=True explicitly wipes it.
    api_key: str | None = None
    clear_api_key: bool = False


class AIProviderConfigResponse(BaseModel):
    id: str
    name: str
    project_id: str | None  # None = portal-wide (admin-managed); set = that project's own key
    provider: AIProvider
    model_name: str | None
    base_url: str | None
    temperature: float
    is_active: bool
    has_api_key: bool  # never the encrypted or raw key itself
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
        return cls(
            id=str(config.id),
            name=config.name,
            project_id=config.project_id,
            provider=config.provider,
            model_name=config.model_name,
            base_url=config.base_url,
            temperature=config.temperature,
            is_active=config.is_active,
            has_api_key=config.api_key_encrypted is not None,
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

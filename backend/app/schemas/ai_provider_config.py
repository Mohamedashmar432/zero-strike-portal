from datetime import datetime
from typing import Literal

from pydantic import BaseModel

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


class AIProviderTestRequest(BaseModel):
    provider: AIProvider
    model_name: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.0


class AIProviderTestResponse(BaseModel):
    success: Literal[True] = True
    message: str

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class McpTokenCreateRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    expires_in_days: Literal[7, 30, 90] = 30


class McpTokenResponse(BaseModel):
    id: str
    label: str
    prefix: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    last_used_ip: str | None = None
    is_active: bool


class McpTokenCreateResponse(McpTokenResponse):
    raw_token: str

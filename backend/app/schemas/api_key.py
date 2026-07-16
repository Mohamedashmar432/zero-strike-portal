from datetime import datetime

from pydantic import BaseModel, Field

from app.models.api_key import ApiKeyScope


class ApiKeyCreateRequest(BaseModel):
    project_id: str
    label: str
    expires_in_days: int = Field(ge=1, le=365)


class ApiKeyCreateResponse(BaseModel):
    id: str
    project_id: str
    label: str
    prefix: str
    raw_token: str
    created_at: datetime
    expires_at: datetime


class ApiKeyResponse(BaseModel):
    id: str
    project_id: str
    label: str
    prefix: str
    scope: ApiKeyScope
    created_by: str
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    last_used_ip: str | None
    is_active: bool


class ApiKeyValidateRequest(BaseModel):
    token: str


class ApiKeyValidateResponse(BaseModel):
    project_id: str
    key_id: str
    expires_at: datetime

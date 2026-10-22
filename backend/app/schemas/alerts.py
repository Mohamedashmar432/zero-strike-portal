from typing import Literal

from pydantic import BaseModel, EmailStr, Field

AlertTrigger = Literal["critical", "high", "vulnerable_package", "scan_failed"]


class ProjectAlertsResponse(BaseModel):
    webhook_enabled: bool
    webhook_configured: bool
    webhook_host: str | None  # never the URL: the path is the secret
    email_enabled: bool
    emails: list[str]
    triggers: list[AlertTrigger]


class ProjectAlertsUpdateRequest(BaseModel):
    # webhook_url: omitted = keep the stored one, "" = remove it.
    webhook_url: str | None = None
    webhook_enabled: bool | None = None
    email_enabled: bool | None = None
    emails: list[EmailStr] | None = Field(None, max_length=3)
    triggers: list[AlertTrigger] | None = None


class GlobalAlertsResponse(BaseModel):
    webhook_enabled: bool
    webhook_configured: bool
    webhook_host: str | None


class GlobalAlertsUpdateRequest(BaseModel):
    webhook_url: str | None = None
    webhook_enabled: bool | None = None

from typing import Literal

from pydantic import BaseModel, EmailStr, Field

AlertTrigger = Literal["critical", "high", "vulnerable_package", "scan_failed"]


LiveAlertMinSeverity = Literal["critical", "high", "medium", "off"]


class ProjectAlertsResponse(BaseModel):
    webhook_enabled: bool
    webhook_configured: bool
    webhook_host: str | None  # never the URL: the path is the secret
    email_enabled: bool
    emails: list[str]
    triggers: list[AlertTrigger]
    # Live dependency alerts: the project's own choice (None = inherit), what actually applies after the
    # tighten-only rule, and the workspace floor the UI needs to disable looser options.
    live_alert_min_severity: LiveAlertMinSeverity | None
    live_alert_effective: LiveAlertMinSeverity
    workspace_live_alert_min_severity: LiveAlertMinSeverity


class ProjectAlertsUpdateRequest(BaseModel):
    # webhook_url: omitted = keep the stored one, "" = remove it.
    webhook_url: str | None = None
    webhook_enabled: bool | None = None
    email_enabled: bool | None = None
    emails: list[EmailStr] | None = Field(None, max_length=3)
    triggers: list[AlertTrigger] | None = None
    # Omitted = unchanged; "inherit" = follow the workspace setting (stored as None).
    live_alert_min_severity: Literal["inherit", "critical", "high", "medium", "off"] | None = None


class GlobalAlertsResponse(BaseModel):
    webhook_enabled: bool
    webhook_configured: bool
    webhook_host: str | None


class GlobalAlertsUpdateRequest(BaseModel):
    webhook_url: str | None = None
    webhook_enabled: bool | None = None

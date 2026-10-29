"""A named outbound webhook (Teams) with its own event and project routing
(docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 9). The URL is a bearer secret: encrypted at
rest, only its host is ever returned."""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WebhookChannel(Document):
    name: str
    url_enc: str
    enabled: bool = True
    events: list[str] = Field(default_factory=list)
    # Empty = every project. A non-empty list also excludes events that name no project.
    project_ids: list[str] = Field(default_factory=list)
    include_digest: bool = False
    # True for the channel created from WorkspaceSettings.alert_webhook_enc; while it exists,
    # alert_service.send_global stands down so the same URL is never posted twice.
    migrated_from_workspace: bool = False
    last_delivery_at: datetime | None = None
    last_status: Literal["ok", "error"] | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    class Settings:
        name = "webhook_channels"

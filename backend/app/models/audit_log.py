from datetime import datetime, timezone
from typing import Literal

from beanie import Document, Indexed
from pydantic import Field


class AuditLog(Document):
    actor_type: Literal["user", "api_key", "system"]
    actor_user_id: str | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    project_id: Indexed(str) | None = None  # type: ignore[valid-type]
    metadata: dict = Field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "audit_logs"
        indexes = ["created_at", "actor_user_id", "action"]

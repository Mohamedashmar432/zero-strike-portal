"""Singleton: the scheduled Teams digest's configuration and its send ledger."""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field


class DigestSettings(Document):
    enabled: bool = False
    frequency: Literal["daily", "weekly"] = "daily"
    hour_utc: int = 3
    minute_utc: int = 30  # 09:00 IST
    weekday: int = 0  # 0 = Monday; weekly only
    project_ids: list[str] = Field(default_factory=list)  # empty = every project
    include_stale_projects: bool = True
    # Period key of the last claimed send ("D:2026-10-28" / "W:2026-10-26"); the atomic claim in
    # digest_service.claim_slot is what stops a restart or second replica double-sending.
    last_sent_for: str | None = None
    last_sent_at: datetime | None = None
    last_status: Literal["sent", "error"] | None = None
    last_error: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "digest_settings"

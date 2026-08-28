"""One delivered in-app notification, per recipient.

Fanned out at write time (one document per recipient) rather than stored once and joined
against membership at read time. Read is the hot path — every dashboard poll asks "what is
unread for me" — and membership can change after the fact, so a stored row is also the only
way an alert stays visible to the person who was a member when it fired.

Expires via a TTL index at `expires_at`, same treatment as AIUsageEvent: a notification
nobody read within the window is noise, and the collection must not grow without bound.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

NotificationSeverity = Literal["info", "success", "warning", "error"]

RETENTION_DAYS = 90


def _default_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=RETENTION_DAYS)


class Notification(Document):
    user_id: str
    event: str  # a key from app.core.notification_events
    title: str
    body: str = ""
    severity: NotificationSeverity = "info"
    project_id: str | None = None
    # Frontend-relative path the notification links to, e.g. "/scans/{id}". Stored rather
    # than reconstructed, so a notification survives a route rename with a dead-but-honest
    # link instead of a wrong one built from stale assumptions.
    link: str | None = None
    read_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = Field(default_factory=_default_expiry)

    class Settings:
        name = "notifications"
        indexes = [
            # The list query: this user's notifications, newest first.
            IndexModel([("user_id", 1), ("created_at", -1)]),
            # The unread-count query, which runs on every poll tick.
            IndexModel([("user_id", 1), ("read_at", 1)]),
            IndexModel([("expires_at", 1)], expireAfterSeconds=0),
        ]

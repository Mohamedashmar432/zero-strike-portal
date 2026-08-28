from datetime import datetime

from pydantic import BaseModel, field_validator

from app.core.notification_events import EVENT_KEYS


def _known_events(v: list[str] | None) -> list[str] | None:
    """Reject event keys that nothing emits — a saved subscription to a non-existent event
    is a switch the user believes is doing something."""
    if v is None:
        return v
    bad = sorted(set(v) - EVENT_KEYS)
    if bad:
        raise ValueError(f"Unknown notification events: {bad}")
    return list(dict.fromkeys(v))


class NotificationOut(BaseModel):
    id: str
    event: str
    title: str
    body: str
    severity: str
    project_id: str | None
    link: str | None
    read_at: datetime | None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationOut]
    unread_count: int


class NotificationEventOut(BaseModel):
    key: str
    label: str
    description: str
    audience: str


class NotificationPreferencesResponse(BaseModel):
    events: list[NotificationEventOut]
    in_app: list[str]
    email: list[str]
    # Email is built and wired but no-ops until SMTP is configured. Surfaced so the page can
    # say so instead of implying mail is going out.
    email_delivery_configured: bool


class NotificationPreferencesUpdateRequest(BaseModel):
    in_app: list[str] | None = None
    email: list[str] | None = None

    _check_in_app = field_validator("in_app")(_known_events)
    _check_email = field_validator("email")(_known_events)


class MarkReadRequest(BaseModel):
    # None marks every unread notification read.
    notification_id: str | None = None

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.notification_events import EVENT_KEYS


def _check_events(events: list[str] | None) -> list[str] | None:
    if events is None:
        return None
    unknown = sorted(set(events) - EVENT_KEYS)
    if unknown:
        raise ValueError(f"Unknown event(s): {', '.join(unknown)}")
    return list(dict.fromkeys(events))  # de-duplicate, keep order


class ChannelCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2000)
    enabled: bool = True
    events: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    include_digest: bool = False

    _events = field_validator("events")(_check_events)


class ChannelUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=80)
    url: str | None = Field(None, min_length=1, max_length=2000)  # omitted = unchanged
    enabled: bool | None = None
    events: list[str] | None = None
    project_ids: list[str] | None = None
    include_digest: bool | None = None

    _events = field_validator("events")(_check_events)


class ChannelResponse(BaseModel):
    """The URL itself is never returned -- only its host."""

    id: str
    name: str
    url_host: str | None
    enabled: bool
    events: list[str]
    project_ids: list[str]
    include_digest: bool
    last_delivery_at: datetime | None
    last_status: Literal["ok", "error"] | None
    last_error: str | None
    created_at: datetime


class ChannelEvent(BaseModel):
    key: str
    label: str
    description: str
    audience: Literal["project", "admin"]
    group: str


class ChannelTestResponse(BaseModel):
    ok: bool
    status: int | None
    error: str | None

from typing import Literal

from pydantic import BaseModel, Field


class CollectionCount(BaseModel):
    name: str
    count: int


class CategoryStats(BaseModel):
    key: str
    label: str
    description: str
    destructive: bool
    implies: list[str]
    total: int
    collections: list[CollectionCount]


class DataStatsResponse(BaseModel):
    project_id: str | None = None
    categories: list[CategoryStats]


class PurgeRequest(BaseModel):
    categories: list[str] = Field(min_length=1)
    # Scope the wipe to one project; None means portal-wide.
    project_id: str | None = None
    # Typed by the admin in the UI. A Literal so a malformed client gets a 422 before
    # anything is deleted, rather than the handler having to remember to check.
    confirm: Literal["DELETE"]


class PurgeResponse(BaseModel):
    # Categories actually purged, after expanding `implies`.
    categories: list[str]
    deleted: dict[str, int]
    total_deleted: int


class ReapResponse(BaseModel):
    reaped: bool

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ProjectCreateRequest(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_archived: bool | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    owner_id: str
    is_archived: bool
    scan_count: int
    last_scan_at: datetime | None
    created_at: datetime
    updated_at: datetime
    my_role: Literal["owner", "collaborator", "admin"]

from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from pymongo import IndexModel


class Project(Document):
    name: Indexed(str)  # type: ignore[valid-type]
    description: str | None = None
    owner_id: Indexed(str)  # type: ignore[valid-type]
    is_archived: bool = False
    scan_count: int = 0
    last_scan_at: datetime | None = None
    # None = inherit the workspace-wide default (see report_template_service, added in a
    # later task).
    report_template: Literal["standard", "executive"] | None = None
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "projects"
        indexes = [IndexModel([("owner_id", 1), ("is_archived", 1)])]  # standard list-view filter

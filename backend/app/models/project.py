from datetime import datetime

from beanie import Document, Indexed


class Project(Document):
    name: Indexed(str)  # type: ignore[valid-type]
    description: str | None = None
    owner_id: Indexed(str)  # type: ignore[valid-type]
    is_archived: bool = False
    scan_count: int = 0
    last_scan_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "projects"

from datetime import datetime
from typing import Literal

from beanie import Document
from pymongo import IndexModel


class ProjectMember(Document):
    project_id: str
    user_id: str | None = None
    invited_email: str
    role: Literal["owner", "collaborator"] = "collaborator"
    invited_by: str
    invited_at: datetime
    accepted_at: datetime | None = None

    class Settings:
        name = "project_members"
        indexes = [
            IndexModel([("project_id", 1), ("invited_email", 1)], unique=True),
            IndexModel([("user_id", 1)]),
        ]

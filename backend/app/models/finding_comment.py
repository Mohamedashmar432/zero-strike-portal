"""Team comment on a finding (see docs/AI_AUTOFIX_DESIGN.md, team controls).

A note any project member can leave on a finding so teammates reviewing the AI fix get context.
Author is stored by id only (resolved to a display email at read time) — no PII duplicated at rest.
"""

from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class FindingComment(Document):
    finding_id: str
    scan_id: str
    project_id: str
    author_user_id: str
    body: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_finding_comments"
        indexes = [
            IndexModel([("finding_id", 1), ("created_at", 1)]),
            IndexModel([("scan_id", 1)]),
            IndexModel([("project_id", 1)]),
        ]

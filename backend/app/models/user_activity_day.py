"""One row per (user, UTC day) the user made an authenticated request -- the honest measure of
"active" (docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 5). Written only by
`activity_service.touch`, throttled so it is never a write per request."""

from datetime import datetime

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

RETENTION_DAYS = 400


class UserActivityDay(Document):
    user_id: str
    day: str  # "YYYY-MM-DD", UTC
    # Projects where the user acted *as a member* that day. Portal-admin access to a project they
    # are not a member of is deliberately not recorded here.
    project_ids: list[str] = Field(default_factory=list)
    first_seen_at: datetime
    last_seen_at: datetime

    class Settings:
        name = "user_activity_days"
        indexes = [
            IndexModel([("user_id", 1), ("day", 1)], unique=True),
            IndexModel([("day", 1)]),
            IndexModel([("first_seen_at", 1)], expireAfterSeconds=RETENTION_DAYS * 86400, name="ttl"),
        ]

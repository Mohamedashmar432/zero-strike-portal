"""First-party user activity (docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 5).

`touch` is called from the auth dependency and from project membership checks, i.e. on nearly every
request, so it is throttled by an in-process seen-set: at most one upsert per (user, day, project)
per replica per day. A failure is logged and swallowed -- recording activity must never fail the
request it describes.
"""

from datetime import datetime, timezone

import structlog
from bson import ObjectId

from app.models.user import User
from app.models.user_activity_day import UserActivityDay

logger = structlog.get_logger(__name__)

# ponytail: per-process; a restart or second replica re-upserts once, which is idempotent.
_seen: set[tuple[str, str, str | None]] = set()
_seen_day: str | None = None


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def reset() -> None:
    global _seen_day
    _seen.clear()
    _seen_day = None


def already_seen(user_id: str, project_id: str | None = None) -> bool:
    return (user_id, today(), project_id) in _seen


async def touch(user_id: str, project_id: str | None = None) -> None:
    global _seen_day
    try:
        day = today()
        if day != _seen_day:  # a new UTC day: yesterday's keys can never match again
            _seen.clear()
            _seen_day = day
        key = (user_id, day, project_id)
        if key in _seen:
            return
        now = datetime.now(timezone.utc)
        update: dict = {"$set": {"last_seen_at": now}, "$setOnInsert": {"first_seen_at": now}}
        if project_id:
            update["$addToSet"] = {"project_ids": project_id}
        else:
            update["$setOnInsert"]["project_ids"] = []
        await UserActivityDay.get_pymongo_collection().update_one(
            {"user_id": user_id, "day": day}, update, upsert=True
        )
        if project_id is None:
            await User.get_pymongo_collection().update_one(
                {"_id": ObjectId(user_id)}, {"$set": {"last_seen_at": now}}
            )
        _seen.add(key)
    except Exception:
        logger.warning("activity write failed", exc_info=True)

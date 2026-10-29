"""Per-project monthly cloud-scan limit (docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md).

A cloud scan counts the moment it is created, for the calendar month (UTC) it was created in, unless
`Scan.quota_exempt` marks it as the portal's own failure. CI/CD scans are never counted. The only
enforcement point is `scan_service.enqueue_repo_scan`, via `ensure_available`.
"""

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core.config import settings
from app.models.project import Project
from app.models.scan import Scan
from app.schemas.project import CloudScanQuota


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return datetime(now.year, now.month, 1, tzinfo=timezone.utc)


def _next_month(start: datetime) -> datetime:
    return datetime(start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=timezone.utc)


def effective_limit(project: Project) -> int:
    limit = project.cloud_scan_monthly_limit
    return settings.cloud_scan_monthly_limit_default if limit is None else limit


def _quota(project: Project, used: int) -> CloudScanQuota:
    start = month_start()
    limit = effective_limit(project)
    return CloudScanQuota(
        used=used,
        limit=limit,
        remaining=max(0, limit - used),
        period_start=start,
        resets_at=_next_month(start),
        is_default=project.cloud_scan_monthly_limit is None,
    )


async def usage(project: Project) -> CloudScanQuota:
    used = await Scan.find(
        Scan.project_id == str(project.id),
        Scan.scan_type == "cloud",
        Scan.created_at >= month_start(),
        {"quota_exempt": {"$ne": True}},
    ).count()
    return _quota(project, used)


async def usage_many(projects: list[Project]) -> dict[str, CloudScanQuota]:
    """One grouped count for a whole list page, rather than a query per project."""
    pipeline = [
        {
            "$match": {
                "project_id": {"$in": [str(p.id) for p in projects]},
                "scan_type": "cloud",
                "created_at": {"$gte": month_start()},
                "quota_exempt": {"$ne": True},
            }
        },
        {"$group": {"_id": "$project_id", "n": {"$sum": 1}}},
    ]
    used = {row["_id"]: row["n"] async for row in Scan.get_pymongo_collection().aggregate(pipeline)}
    return {str(p.id): _quota(p, used.get(str(p.id), 0)) for p in projects}


async def ensure_available(project: Project) -> None:
    quota = await usage(project)
    if quota.limit == 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cloud scanning is paused for this project. Ask a portal admin to set a limit.",
        )
    if quota.used >= quota.limit:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cloud scan limit reached: {quota.used}/{quota.limit} this month. "
            "Ask a portal admin to raise this project's limit.",
        )

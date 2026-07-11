from beanie.operators import In

from app.models.finding import Finding
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.scan import Scan
from app.models.user import User
from app.schemas.dashboard import DashboardStatsResponse, SeverityCounts


async def _severity_groups(pipeline: list[dict]) -> list[dict]:
    """Run the severity aggregation pipeline against the raw collection.

    Beanie's Document.aggregate() assumes a pymongo-native async collection whose
    .aggregate() itself returns an awaitable. This backend's Mongo client is classic
    motor.motor_asyncio.AsyncIOMotorClient (see app/db/mongo.py), whose .aggregate()
    returns the cursor directly (not awaitable) — same for the mongomock_motor test
    double. scan_queue_service.py already drops to get_pymongo_collection() for raw
    collection calls for the same reason; mirror that here instead of Document.aggregate().
    """
    cursor = Finding.get_pymongo_collection().aggregate(pipeline)
    return await cursor.to_list(length=None)


def _to_severity_counts(groups: list[dict]) -> SeverityCounts:
    counts = SeverityCounts()
    for group in groups:
        severity = group.get("_id")
        if severity is None or not hasattr(counts, severity):
            # Findings with no severity set (or any unexpected value) don't fit the
            # fixed set of buckets — skip rather than crash.
            continue
        setattr(counts, severity, group.get("count", 0))
    return counts


async def get_stats(user: User) -> DashboardStatsResponse:
    if user.role == "admin":
        project_count = await Project.count()
        scan_count = await Scan.count()
        severity_groups = await _severity_groups([{"$group": {"_id": "$severity", "count": {"$sum": 1}}}])
        return DashboardStatsResponse(
            project_count=project_count,
            scan_count=scan_count,
            findings_by_severity=_to_severity_counts(severity_groups),
        )

    memberships = await ProjectMember.find(ProjectMember.user_id == str(user.id)).to_list()
    project_ids = [m.project_id for m in memberships]

    if not project_ids:
        return DashboardStatsResponse(
            project_count=0, scan_count=0, findings_by_severity=SeverityCounts()
        )

    scan_count = await Scan.find(In(Scan.project_id, project_ids)).count()
    severity_groups = await _severity_groups(
        [
            {"$match": {"project_id": {"$in": project_ids}}},
            {"$group": {"_id": "$severity", "count": {"$sum": 1}}},
        ]
    )
    return DashboardStatsResponse(
        project_count=len(project_ids),
        scan_count=scan_count,
        findings_by_severity=_to_severity_counts(severity_groups),
    )

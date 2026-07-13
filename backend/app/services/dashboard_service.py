from beanie import PydanticObjectId
from beanie.operators import In

from app.models.finding import Finding
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.scan import Scan
from app.models.user import User
from app.schemas.dashboard import DashboardStatsResponse, RecentScanItem, SeverityCounts

RECENT_SCANS_LIMIT = 5


async def _recent_scans(project_ids: list[str] | None) -> list[RecentScanItem]:
    """project_ids=None means unscoped (admin sees every scan)."""
    query = Scan.find(In(Scan.project_id, project_ids)) if project_ids is not None else Scan.find_all()
    scans = await query.sort(-Scan.created_at).limit(RECENT_SCANS_LIMIT).to_list()
    if not scans:
        return []

    scan_ids = [str(s.id) for s in scans]
    per_scan_groups = await _severity_groups(
        [
            {"$match": {"scan_id": {"$in": scan_ids}}},
            {"$group": {"_id": {"scan_id": "$scan_id", "severity": "$severity"}, "count": {"$sum": 1}}},
        ]
    )
    counts_by_scan: dict[str, SeverityCounts] = {}
    for group in per_scan_groups:
        scan_id = group["_id"]["scan_id"]
        severity = group["_id"].get("severity")
        counts = counts_by_scan.setdefault(scan_id, SeverityCounts())
        if severity is not None and hasattr(counts, severity):
            setattr(counts, severity, group.get("count", 0))

    project_object_ids = [PydanticObjectId(s.project_id) for s in scans]
    projects_by_id = {str(p.id): p for p in await Project.find(In(Project.id, project_object_ids)).to_list()}

    return [
        RecentScanItem(
            scan_id=str(s.id),
            project_id=s.project_id,
            project_name=projects_by_id[s.project_id].name if s.project_id in projects_by_id else "Unknown project",
            status=s.status,
            scan_type=s.scan_type,
            created_at=s.created_at,
            findings_by_severity=counts_by_scan.get(str(s.id), SeverityCounts()),
        )
        for s in scans
    ]


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
            recent_scans=await _recent_scans(None),
        )

    memberships = await ProjectMember.find(ProjectMember.user_id == str(user.id)).to_list()
    project_ids = list({m.project_id for m in memberships})

    if not project_ids:
        return DashboardStatsResponse(
            project_count=0, scan_count=0, findings_by_severity=SeverityCounts(), recent_scans=[]
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
        recent_scans=await _recent_scans(project_ids),
    )

"""Aggregated findings/scan/repo stats per project — powers the projects list table, a
project's Overview tab, per-repo scan history, and OWASP category summaries. Every query
here is a raw pymongo aggregation via get_pymongo_collection() (not Document.aggregate(),
which isn't awaitable on this Motor client — see dashboard_service._severity_groups for
the same pattern) rather than a new service/infra layer."""

from beanie.operators import And, Eq, Or

from app.core.owasp import OWASP_CODES_ORDERED
from app.models.finding import Finding
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.models.user import User
from app.schemas.dashboard import SeverityCounts
from app.schemas.project import ProjectStatsItem, ScanHistoryItem, ScanStatusCounts
from app.services import project_repo_service

_RISK_SEVERITIES = ["critical", "high"]


async def _aggregate(model, pipeline: list[dict]) -> list[dict]:
    cursor = model.get_pymongo_collection().aggregate(pipeline)
    return await cursor.to_list(length=None)


def _severity_counts_from_groups(groups: list[dict], key: str) -> dict[str, SeverityCounts]:
    by_key: dict[str, SeverityCounts] = {}
    for g in groups:
        k = g["_id"][key]
        severity = g["_id"].get("severity")
        counts = by_key.setdefault(k, SeverityCounts())
        if severity is not None and hasattr(counts, severity):
            setattr(counts, severity, g.get("count", 0))
    return by_key


async def _resolve_project_ids(user: User, project_ids: list[str] | None) -> list[str]:
    if user.role == "admin":
        if project_ids is not None:
            return project_ids
        return [str(p.id) for p in await Project.find_all().to_list()]

    memberships = await ProjectMember.find(ProjectMember.user_id == str(user.id)).to_list()
    member_ids = {m.project_id for m in memberships}
    if project_ids is not None:
        return [pid for pid in project_ids if pid in member_ids]
    return list(member_ids)


async def get_projects_stats(user: User, project_ids: list[str] | None = None) -> dict[str, ProjectStatsItem]:
    ids = await _resolve_project_ids(user, project_ids)
    if not ids:
        return {}

    total_groups = await _aggregate(
        Finding,
        [
            {"$match": {"project_id": {"$in": ids}}},
            {"$group": {"_id": "$project_id", "count": {"$sum": 1}}},
        ],
    )
    total_by_project = {g["_id"]: g["count"] for g in total_groups}

    severity_groups = await _aggregate(
        Finding,
        [
            {"$match": {"project_id": {"$in": ids}}},
            {"$group": {"_id": {"project_id": "$project_id", "severity": "$severity"}, "count": {"$sum": 1}}},
        ],
    )
    severity_by_project = _severity_counts_from_groups(severity_groups, "project_id")

    risk_groups = await _aggregate(
        Finding,
        [
            {
                "$match": {
                    "project_id": {"$in": ids},
                    "severity": {"$in": _RISK_SEVERITIES},
                    "project_repo_id": {"$ne": None},
                }
            },
            {"$group": {"_id": "$project_id", "repos": {"$addToSet": "$project_repo_id"}}},
        ],
    )
    risk_repo_by_project = {g["_id"]: len(g["repos"]) for g in risk_groups}

    scan_status_groups = await _aggregate(
        Scan,
        [
            {"$match": {"project_id": {"$in": ids}}},
            {"$group": {"_id": {"project_id": "$project_id", "status": "$status"}, "count": {"$sum": 1}}},
        ],
    )
    scan_status_by_project: dict[str, ScanStatusCounts] = {}
    for g in scan_status_groups:
        pid = g["_id"]["project_id"]
        s = g["_id"].get("status")
        counts = scan_status_by_project.setdefault(pid, ScanStatusCounts())
        if s is not None and hasattr(counts, s):
            setattr(counts, s, g.get("count", 0))

    repo_count_groups = await _aggregate(
        ProjectRepo,
        [
            {"$match": {"project_id": {"$in": ids}}},
            {"$group": {"_id": "$project_id", "count": {"$sum": 1}}},
        ],
    )
    repo_count_by_project = {g["_id"]: g["count"] for g in repo_count_groups}

    return {
        pid: ProjectStatsItem(
            project_id=pid,
            total_findings=total_by_project.get(pid, 0),
            findings_by_severity=severity_by_project.get(pid, SeverityCounts()),
            scan_status_counts=scan_status_by_project.get(pid, ScanStatusCounts()),
            risk_repo_count=risk_repo_by_project.get(pid, 0),
            total_repo_count=repo_count_by_project.get(pid, 0),
        )
        for pid in ids
    }


async def get_repo_scan_history(project_id: str, repo_id: str, limit: int = 30) -> list[ScanHistoryItem]:
    repo = await project_repo_service.get_project_repo_or_404(project_id, repo_id)

    # Best-effort fallback for scans ingested before project_repo_id existed: match by the
    # repo's clone_url when project_repo_id wasn't stamped on the scan.
    scans = (
        await Scan.find(
            Scan.project_id == project_id,
            Or(Eq(Scan.project_repo_id, repo_id), And(Eq(Scan.project_repo_id, None), Eq(Scan.repo_url, repo.clone_url))),
        )
        .sort(-Scan.created_at)
        .limit(limit)
        .to_list()
    )
    scans.reverse()  # oldest -> newest, for charting left-to-right
    if not scans:
        return []

    scan_ids = [str(s.id) for s in scans]
    groups = await _aggregate(
        Finding,
        [
            {"$match": {"scan_id": {"$in": scan_ids}}},
            {"$group": {"_id": {"scan_id": "$scan_id", "severity": "$severity"}, "count": {"$sum": 1}}},
        ],
    )
    counts_by_scan = _severity_counts_from_groups(groups, "scan_id")

    return [
        ScanHistoryItem(
            scan_id=str(s.id),
            status=s.status,
            created_at=s.created_at,
            completed_at=s.completed_at,
            total_findings=sum(counts_by_scan.get(str(s.id), SeverityCounts()).model_dump().values()),
            findings_by_severity=counts_by_scan.get(str(s.id), SeverityCounts()),
        )
        for s in scans
    ]


async def get_owasp_summary(project_id: str, project_repo_id: str | None = None) -> dict[str, int]:
    match: dict = {"project_id": project_id}
    if project_repo_id:
        match["project_repo_id"] = project_repo_id
    groups = await _aggregate(
        Finding,
        [
            {"$match": match},
            {"$unwind": "$owasp"},
            {"$group": {"_id": "$owasp", "count": {"$sum": 1}}},
        ],
    )
    by_owasp = dict.fromkeys(OWASP_CODES_ORDERED, 0)
    for g in groups:
        code = g["_id"]
        if code in by_owasp:
            by_owasp[code] = g["count"]
    return by_owasp

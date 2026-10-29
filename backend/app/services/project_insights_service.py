"""Admin view of what every project is doing and what is failing
(docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md). Read-only. Counts are one `$group` over the raw scans
collection -- not a query per project."""

from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import HTTPException

from app.core.repo_url import sanitize_repo_url
from app.core.timeutils import as_utc
from app.models.audit_log import AuditLog
from app.models.finding import NOT_SUPPRESSED, Finding
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.models.user import User
from app.models.user_activity_day import UserActivityDay
from app.schemas.project_insights import (
    ActiveUser,
    CveRef,
    InsightsTotals,
    NewCves,
    ProjectActivityResponse,
    TimelineEvent,
    UsersBlock,
    LastError,
    ProjectInsightsResponse,
    ProjectInsightsRow,
    ScanCounts,
    ScanRequestItem,
    ScanRequestsResponse,
)
from app.services import cloud_scan_quota_service

_MAX_RANGE = timedelta(days=366)
_DEFAULT_RANGE = timedelta(days=30)
_ACTIVE = {"cloud": {"queued", "running"}, "cicd": {"pending", "running"}}


def window(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    """[since, until) in UTC; defaults to the last 30 days."""
    until = (until if until.tzinfo else until.replace(tzinfo=timezone.utc)) if until else datetime.now(timezone.utc)
    since = (since if since.tzinfo else since.replace(tzinfo=timezone.utc)) if since else until - _DEFAULT_RANGE
    if until <= since:
        raise HTTPException(422, "`until` must be after `since`.")
    if until - since > _MAX_RANGE:
        raise HTTPException(422, "A date range can span at most 366 days.")
    return since, until


def _add(counts: ScanCounts, scan_type: str, scan_status: str, n: int) -> None:
    counts.total += n
    if scan_status == "completed":
        counts.completed += n
    elif scan_status == "failed":
        counts.failed += n
    if scan_status in _ACTIVE[scan_type]:
        counts.active += n


async def scan_counts(since: datetime, until: datetime) -> dict[str, dict[str, ScanCounts]]:
    """{project_id: {"cloud": ScanCounts, "cicd": ScanCounts}} for scans created in [since, until)."""
    pipeline = [
        {"$match": {"created_at": {"$gte": since, "$lt": until}}},
        {"$group": {"_id": {"p": "$project_id", "t": "$scan_type", "s": "$status"}, "n": {"$sum": 1}}},
    ]
    counts: dict[str, dict[str, ScanCounts]] = {}
    async for row in Scan.get_pymongo_collection().aggregate(pipeline):
        key = row["_id"]
        per_type = counts.setdefault(key["p"], {"cloud": ScanCounts(), "cicd": ScanCounts()})
        _add(per_type[key["t"]], key["t"], key["s"], row["n"])
    return counts


_SEVERITY_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


async def new_cves(
    project_ids: list[str] | None, since: datetime, until: datetime
) -> dict[str, list[tuple[str, str, datetime]]]:
    """Advisory ids (CVE/GHSA/...) on dependency findings that a project first reported inside
    [since, until): `{project_id: [(advisory_id, severity, first_seen)]}`, newest first.

    One grouped pass: an id is new when the project's *earliest* finding carrying it was created in
    the window; an id seen before `since` is not new, however often it recurs after. Findings are
    rewritten per scan, so "earliest" is the first scan that reported it. Suppressed findings do not
    count. The ids come from OSV.dev lookups made at scan time -- the portal holds no CVE feed.
    """
    match: dict = {"kind": "sca", "dependency.advisory_ids": {"$exists": True, "$ne": []}, **NOT_SUPPRESSED}
    if project_ids is not None:
        match["project_id"] = {"$in": project_ids}
    pipeline = [
        {"$match": match},
        {"$unwind": "$dependency.advisory_ids"},
        {
            "$group": {
                "_id": {"p": "$project_id", "a": "$dependency.advisory_ids"},
                "first": {"$min": "$created_at"},
                "sevs": {"$addToSet": "$severity"},
            }
        },
    ]
    out: dict[str, list[tuple[str, str, datetime]]] = {}
    async for row in Finding.get_pymongo_collection().aggregate(pipeline):
        first = as_utc(row["first"])
        if not (since <= first < until):
            continue
        sev = max((v for v in row["sevs"] if v), key=lambda v: _SEVERITY_RANK.get(v, 0), default="info")
        out.setdefault(row["_id"]["p"], []).append((row["_id"]["a"], sev, first))
    for found in out.values():
        found.sort(key=lambda t: t[2], reverse=True)
    return out


def new_cves_block(found: list[tuple[str, str, datetime]]) -> NewCves:
    return NewCves(count=len(found), latest=[CveRef(id=a, severity=sev) for a, sev, _ in found[:2]])


async def users_block(since: datetime, until: datetime) -> UsersBlock:
    users = User.get_pymongo_collection()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    activity = UserActivityDay.get_pymongo_collection()
    active_in_window = len(await activity.distinct("user_id", {"day": _day_range(since, until)}))
    active_today = len(await activity.distinct("user_id", {"day": today_start.strftime("%Y-%m-%d")}))
    return UsersBlock(
        total=await users.count_documents({}),
        registered_in_window=await users.count_documents({"created_at": {"$gte": since, "$lt": until}}),
        registered_today=await users.count_documents({"created_at": {"$gte": today_start}}),
        active_in_window=active_in_window,
        active_today=active_today,
        never_signed_in=await users.count_documents({"last_login_at": None, "last_seen_at": None}),
        pending_approval=await users.count_documents({"approval_status": "pending"}),
        disabled=await users.count_documents({"is_active": False}),
    )


def _day_range(since: datetime, until: datetime) -> dict:
    return {"$gte": since.strftime("%Y-%m-%d"), "$lte": (until - timedelta(microseconds=1)).strftime("%Y-%m-%d")}


async def _active_users_per_project(since: datetime, until: datetime) -> dict[str, int]:
    pipeline = [
        {"$match": {"day": _day_range(since, until)}},
        {"$unwind": "$project_ids"},
        {"$group": {"_id": "$project_ids", "users": {"$addToSet": "$user_id"}}},
    ]
    return {
        row["_id"]: len(row["users"])
        async for row in UserActivityDay.get_pymongo_collection().aggregate(pipeline)
    }


async def get_insights(since: datetime, until: datetime) -> ProjectInsightsResponse:
    in_window = {"created_at": {"$gte": since, "$lt": until}}
    # Newest failed scan per project; $first after a newest-first sort picks it.
    error_pipeline = [
        {"$match": {**in_window, "status": "failed", "error_message": {"$ne": None}}},
        {"$sort": {"created_at": -1}},
        {
            "$group": {
                "_id": "$project_id",
                "scan_id": {"$first": {"$toString": "$_id"}},
                "scan_type": {"$first": "$scan_type"},
                "message": {"$first": "$error_message"},
                "at": {"$first": {"$ifNull": ["$completed_at", "$created_at"]}},
            }
        },
    ]
    scans = Scan.get_pymongo_collection()
    counts = await scan_counts(since, until)
    errors = {row["_id"]: row async for row in scans.aggregate(error_pipeline)}
    repo_counts = {
        row["_id"]: row["n"]
        async for row in ProjectRepo.get_pymongo_collection().aggregate(
            [{"$group": {"_id": "$project_id", "n": {"$sum": 1}}}]
        )
    }

    member_counts = {
        row["_id"]: row["n"]
        async for row in ProjectMember.get_pymongo_collection().aggregate(
            [{"$match": {"user_id": {"$ne": None}}}, {"$group": {"_id": "$project_id", "n": {"$sum": 1}}}]
        )
    }
    active_by_project = await _active_users_per_project(since, until)
    cves = await new_cves(None, since, until)
    projects = await Project.find_all().sort(-Project.id).to_list()
    quotas = await cloud_scan_quota_service.usage_many(projects)
    totals = InsightsTotals(
        projects=sum(1 for p in projects if not p.is_archived),
        projects_created=sum(1 for p in projects if since <= as_utc(p.created_at) < until),
        repos=sum(repo_counts.values()),
        cloud=ScanCounts(),
        cicd=ScanCounts(),
    )
    rows = []
    for p in projects:
        pid = str(p.id)
        per_type = counts.get(pid, {"cloud": ScanCounts(), "cicd": ScanCounts()})
        for scan_type in ("cloud", "cicd"):
            roll, mine = getattr(totals, scan_type), per_type[scan_type]
            for field in ("total", "completed", "failed", "active"):
                setattr(roll, field, getattr(roll, field) + getattr(mine, field))
        err = errors.get(pid)
        last_error = (
            LastError(
                scan_id=err["scan_id"], scan_type=err["scan_type"], message=err["message"], at=as_utc(err["at"])
            )
            if err
            else None
        )
        rows.append(
            ProjectInsightsRow(
                project_id=pid,
                name=p.name,
                is_archived=p.is_archived,
                created_at=as_utc(p.created_at),
                repos=repo_counts.get(pid, 0),
                cloud=per_type["cloud"],
                cicd=per_type["cicd"],
                last_scan_at=as_utc(p.last_scan_at),
                last_error=last_error,
                cloud_scan_quota=quotas[pid],
                members=member_counts.get(pid, 0),
                active_users=active_by_project.get(pid, 0),
                new_cves=new_cves_block(cves.get(pid, [])),
            )
        )
    return ProjectInsightsResponse(
        since=since, until=until, totals=totals, users=await users_block(since, until), projects=rows
    )


async def project_activity(project: Project, since: datetime, until: datetime, limit: int) -> ProjectActivityResponse:
    """Who used one project and what happened in it, from first-party activity days and the audit log."""
    pid = str(project.id)
    pipeline = [
        {"$match": {"day": _day_range(since, until), "project_ids": pid}},
        {"$group": {"_id": "$user_id", "days": {"$sum": 1}, "last": {"$max": "$last_seen_at"}}},
        {"$sort": {"last": -1}},
    ]
    rows = [r async for r in UserActivityDay.get_pymongo_collection().aggregate(pipeline)]
    audit = (
        await AuditLog.find(
            {
                "$or": [{"project_id": pid}, {"metadata.project_id": pid}],
                "created_at": {"$gte": since, "$lt": until},
            }
        )
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )
    wanted = {r["_id"] for r in rows} | {a.actor_user_id for a in audit if a.actor_user_id}
    valid = [PydanticObjectId(u) for u in wanted if len(u) == 24]
    people = {str(u.id): u for u in await User.find(In(User.id, valid)).to_list()} if valid else {}
    return ProjectActivityResponse(
        project_id=pid,
        name=project.name,
        active_users=[
            ActiveUser(
                user_id=r["_id"],
                email=people[r["_id"]].email if r["_id"] in people else "(deleted user)",
                name=people[r["_id"]].name if r["_id"] in people else "",
                days_active=r["days"],
                last_seen_at=as_utc(r["last"]),
            )
            for r in rows
        ],
        timeline=[
            TimelineEvent(
                at=as_utc(a.created_at),
                action=a.action,
                actor_type=a.actor_type,
                actor_email=people[a.actor_user_id].email if a.actor_user_id in people else None,
                target_type=a.target_type,
                target_id=a.target_id,
                metadata=a.metadata,
            )
            for a in audit
        ],
    )


# Everything a request row shows -- repo_token and the report payload are never read.
_REQUEST_FIELDS = {
    f: 1
    for f in (
        "project_id scan_type triggered_by status stage repo_url branch scan_label ci_provider "
        "ci_build_url error_message created_at started_at completed_at quota_exempt"
    ).split()
}


async def list_requests(
    since: datetime,
    until: datetime,
    *,
    project_id: str | None,
    scan_type: str | None,
    scan_status: str | None,
    limit: int,
    offset: int,
) -> ScanRequestsResponse:
    query: dict = {"created_at": {"$gte": since, "$lt": until}}
    for field, value in (("project_id", project_id), ("scan_type", scan_type), ("status", scan_status)):
        if value:
            query[field] = value
    col = Scan.get_pymongo_collection()
    total = await col.count_documents(query)
    docs = await col.find(query, _REQUEST_FIELDS).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)

    # A project_id that is not an ObjectId can only be a dangling row, never a live project.
    valid = [PydanticObjectId(pid) for pid in {d["project_id"] for d in docs} if len(pid) == 24]
    names = {str(p.id): p.name for p in await Project.find(In(Project.id, valid)).to_list()} if valid else {}
    items = [
        ScanRequestItem(
            scan_id=str(d["_id"]),
            project_id=d["project_id"],
            project_name=names.get(d["project_id"]),
            scan_type=d["scan_type"],
            triggered_by=d.get("triggered_by", "cli"),
            status=d["status"],
            stage=d.get("stage"),
            repo_url=sanitize_repo_url(d.get("repo_url")),
            branch=d.get("branch"),
            scan_label=d.get("scan_label"),
            ci_provider=d.get("ci_provider"),
            ci_build_url=d.get("ci_build_url"),
            error_message=d.get("error_message"),
            created_at=as_utc(d["created_at"]),
            started_at=as_utc(d.get("started_at")),
            completed_at=as_utc(d.get("completed_at")),
            quota_exempt=d.get("quota_exempt", False),
        )
        for d in docs
    ]
    return ScanRequestsResponse(total=total, items=items)

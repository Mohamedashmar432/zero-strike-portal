"""Aggregated findings/scan/repo stats per project — powers the projects list table, a
project's Overview tab, per-repo scan history, and OWASP category summaries. Every query
here is a raw pymongo aggregation via get_pymongo_collection() (not Document.aggregate(),
which isn't awaitable on this Motor client — see dashboard_service._severity_groups for
the same pattern) rather than a new service/infra layer."""

from beanie import PydanticObjectId
from beanie.operators import And, Eq, In, Or

from app.core.owasp import OWASP_CODES_ORDERED
from app.models.finding import Finding
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.models.user import User
from app.schemas.dashboard import SeverityCounts
from app.schemas.project import (
    ProjectScanActivityResponse,
    ProjectStatsItem,
    RepoScanGroup,
    ScanHistoryItem,
    ScanStatusCounts,
)
from app.services import project_repo_service

# Group key used for scans that match no connected repo (legacy/CI/hand-pasted URLs).
_UNLINKED = "__unlinked__"

_RISK_SEVERITIES = ["critical", "high"]
_ALL_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_CI_LABELS = {
    "github_actions": "GitHub Actions",
    "gitlab_ci": "GitLab CI",
    "azure_pipelines": "Azure Pipelines",
}


async def _resolve_scanner_names(scans) -> dict[str, str]:
    """Map created_by user-id -> display name for the scans that carry one (cloud/manual)."""
    oids = []
    for s in scans:
        if s.created_by:
            try:
                oids.append(PydanticObjectId(s.created_by))
            except Exception:
                pass
    if not oids:
        return {}
    users = await User.find(In(User.id, oids)).to_list()
    return {str(u.id): (u.name or u.email) for u in users}


def _scanned_by(scan, names: dict[str, str]) -> str:
    """Who/what started the scan: cloud -> the member's name; CI/CD -> the provider; local -> host."""
    if scan.scan_type == "cicd":
        return _CI_LABELS.get(scan.ci_provider or "", "CI/CD")
    if scan.created_by and scan.created_by in names:
        return names[scan.created_by]
    if scan.scan_type == "local":
        return scan.hostname or "CLI"
    return "Unknown"


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


async def get_severity_by_scan_ids(scan_ids: list[str]) -> dict[str, SeverityCounts]:
    """Batched per-scan severity breakdown for a page of scans -- avoids the scans list
    endpoint needing a per-row report fetch (see frontend ScansTab)."""
    if not scan_ids:
        return {}
    groups = await _aggregate(
        Finding,
        [
            {"$match": {"scan_id": {"$in": scan_ids}}},
            {"$group": {"_id": {"scan_id": "$scan_id", "severity": "$severity"}, "count": {"$sum": 1}}},
        ],
    )
    return _severity_counts_from_groups(groups, "scan_id")


async def reconcile_project_finding_counts() -> int:
    """Recompute the denormalized per-project findings rollup from the findings collection and
    write it onto each Project whose stored counters are stale. Run once at startup: backfills
    projects created before denormalization existed and self-heals any drift. Idempotent — after
    the first boot it writes nothing (no changes to make). Returns the number of projects updated."""
    groups = await _aggregate(
        Finding,
        [{"$group": {"_id": {"project_id": "$project_id", "severity": "$severity"}, "count": {"$sum": 1}}}],
    )
    totals: dict[str, int] = {}
    by_sev: dict[str, dict[str, int]] = {}
    for g in groups:
        pid = g["_id"]["project_id"]
        sev = g["_id"].get("severity")
        totals[pid] = totals.get(pid, 0) + g["count"]
        if sev in _ALL_SEVERITIES:
            by_sev.setdefault(pid, {})[sev] = g["count"]

    updated = 0
    async for p in Project.find_all():
        pid = str(p.id)
        new_total = totals.get(pid, 0)
        new_counts = by_sev.get(pid, {})
        if p.total_findings != new_total or (p.finding_severity_counts or {}) != new_counts:
            p.total_findings = new_total
            p.finding_severity_counts = new_counts
            await p.save()
            updated += 1
    return updated


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

    # total_findings + findings_by_severity come from the denormalized rollup on the Project doc
    # (maintained by report_ingestion_service.ingest), not a per-request aggregation over the whole
    # findings collection. One indexed doc read instead of two full-collection $groups.
    oids = []
    for i in ids:
        try:
            oids.append(PydanticObjectId(i))
        except Exception:
            pass  # skip non-ObjectId ids (synthetic test data) — they have no Project doc
    projects = await Project.find(In(Project.id, oids)).to_list()
    total_by_project: dict[str, int] = {}
    severity_by_project: dict[str, SeverityCounts] = {}
    for p in projects:
        pid = str(p.id)
        total_by_project[pid] = p.total_findings
        counts = SeverityCounts()
        for sev, n in (p.finding_severity_counts or {}).items():
            if hasattr(counts, sev):
                setattr(counts, sev, n)
        severity_by_project[pid] = counts

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


def _add_severity(acc: SeverityCounts, other: SeverityCounts) -> None:
    for field in SeverityCounts.model_fields:
        setattr(acc, field, getattr(acc, field) + getattr(other, field))


async def get_project_scan_activity(project_id: str, limit_per_repo: int = 50) -> ProjectScanActivityResponse:
    """Every scan in the project, grouped by connected repo, each row carrying its per-scan
    severity breakdown -- powers the History tab (trend chart + Snyk-style list). Also computes
    current_findings: the sum of each group's most recent COMPLETED scan (the live posture across
    all repos), not the all-time total. Scans matching no connected repo land in an "Unlinked
    scans" group so nothing is silently dropped."""
    repos = await project_repo_service.list_repos(project_id)
    # Heuristic cap, not a strict per-repo guarantee: bounds a pathological all-time scan count
    # while comfortably covering the realistic case (repos in one project scan at similar
    # cadence). Revisit only if a real project shows an imbalanced-repo gap in this view.
    scans = (
        await Scan.find(Scan.project_id == project_id)
        .sort(-Scan.created_at)
        .limit(limit_per_repo * (len(repos) + 1) * 3)  # +1 = unlinked bucket; x3 = safety margin
        .to_list()
    )

    # repo resolution: exact project_repo_id, else clone_url match for un-stamped legacy scans.
    by_id = {str(r.id): r for r in repos}
    by_clone_url = {r.clone_url: r for r in repos}

    def _resolve_repo_key(scan) -> str:
        if scan.project_repo_id and scan.project_repo_id in by_id:
            return scan.project_repo_id
        if scan.project_repo_id is None and scan.repo_url and scan.repo_url in by_clone_url:
            return str(by_clone_url[scan.repo_url].id)
        return _UNLINKED

    counts_by_scan: dict[str, SeverityCounts] = {}
    if scans:
        groups = await _aggregate(
            Finding,
            [
                {"$match": {"scan_id": {"$in": [str(s.id) for s in scans]}}},
                {"$group": {"_id": {"scan_id": "$scan_id", "severity": "$severity"}, "count": {"$sum": 1}}},
            ],
        )
        counts_by_scan = _severity_counts_from_groups(groups, "scan_id")

    names = await _resolve_scanner_names(scans)

    def _to_item(scan) -> ScanHistoryItem:
        counts = counts_by_scan.get(str(scan.id), SeverityCounts())
        return ScanHistoryItem(
            scan_id=str(scan.id),
            status=scan.status,
            created_at=scan.created_at,
            completed_at=scan.completed_at,
            total_findings=sum(counts.model_dump().values()),
            findings_by_severity=counts,
            scan_type=scan.scan_type,
            scanned_by=_scanned_by(scan, names),
        )

    # Bucket scans (already newest-first) per repo key.
    buckets: dict[str, list[ScanHistoryItem]] = {}
    for scan in scans:
        buckets.setdefault(_resolve_repo_key(scan), []).append(_to_item(scan))

    result_groups: list[RepoScanGroup] = []
    current = SeverityCounts()
    # Connected repos first (even those with no scans yet), then the unlinked bucket if present.
    for repo in repos:
        rid = str(repo.id)
        repo_scans = buckets.get(rid, [])[:limit_per_repo]
        result_groups.append(
            RepoScanGroup(
                repo_id=rid,
                repo_label=repo.label or repo.repo_full_name,
                provider=repo.provider,
                scans=repo_scans,
            )
        )
        latest_completed = next((s for s in repo_scans if s.status == "completed"), None)
        if latest_completed:
            _add_severity(current, latest_completed.findings_by_severity)

    if buckets.get(_UNLINKED):
        unlinked = buckets[_UNLINKED][:limit_per_repo]
        result_groups.append(
            RepoScanGroup(repo_id=None, repo_label="Unlinked scans", provider=None, scans=unlinked)
        )
        latest_completed = next((s for s in unlinked if s.status == "completed"), None)
        if latest_completed:
            _add_severity(current, latest_completed.findings_by_severity)

    return ProjectScanActivityResponse(
        repos=result_groups,
        current_findings=current,
        current_findings_total=sum(current.model_dump().values()),
    )


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

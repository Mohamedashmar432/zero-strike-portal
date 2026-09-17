"""Vulnerability lifecycle HTTP surface: the work-queue list/detail, human status/assignment
transitions, and the per-scan regression read. Stage 1 (app.services.vulnerability_service)
is the only writer of current_*/regression fields via reconcile_scan -- this router only ever
writes the human-triage fields (status, resolution, assignee) it owns outright, and never
touches reconcile_scan's own bookkeeping (first_seen_at, last_regression_*, current_*).
"""

import re
from datetime import datetime, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_current_user
from app.models.audit_log import AuditLog
from app.models.finding import Finding
from app.models.project_member import ProjectMember
from app.models.scan import Scan
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.schemas.common import Page
from app.schemas.vulnerability import (
    RegressionBucket,
    ScanRegressionResponse,
    VulnerabilityActivityEvent,
    VulnerabilityAssignmentUpdateRequest,
    VulnerabilityDetailResponse,
    VulnerabilityOut,
    VulnerabilityScanObservation,
    VulnerabilityStatusUpdateRequest,
)
from app.services import audit_service, project_repo_service, project_service
from app.services import project_stats_service as stats_svc

router = APIRouter(tags=["vulnerabilities"])

# query key -> real Vulnerability field name. Anything else (including no `sort` at all)
# falls back to the default below -- an unrecognized sort key degrading quietly to the
# default is friendlier to a stale frontend build than a 422 on every page load.
_SORT_FIELD_NAMES = {
    "last_seen_at": "last_seen_at",
    "first_seen_at": "first_seen_at",
    "priority": "current_priority_score",
}
_DEFAULT_SORT = "-last_seen_at"
# How many rows per regression bucket the scan-detail response carries. The bucket `count` is
# always the true total -- this only bounds the inlined preview, since the first scan of a large
# repo classifies every finding as "new" and would otherwise serialize thousands of rows.
_REGRESSION_PREVIEW_LIMIT = 25


def _sort_expr(sort: str) -> str:
    desc = sort.startswith("-")
    key = sort[1:] if desc else sort
    if key not in _SORT_FIELD_NAMES:
        return _DEFAULT_SORT
    return f"{'-' if desc else '+'}{_SORT_FIELD_NAMES[key]}"


async def _email_map(user_ids: set[str]) -> dict[str, str]:
    valid = [PydanticObjectId(i) for i in user_ids if i and PydanticObjectId.is_valid(i)]
    if not valid:
        return {}
    users = await User.find(In(User.id, valid)).to_list()
    return {str(u.id): u.email for u in users}


def _to_out(v: Vulnerability, emails: dict[str, str]) -> VulnerabilityOut:
    return VulnerabilityOut(
        id=str(v.id),
        project_id=v.project_id,
        project_repo_id=v.project_repo_id,
        repo_scope_key=v.repo_scope_key,
        fingerprint=v.fingerprint,
        status=v.status,
        resolution_reason=v.resolution_reason,
        resolution_comment=v.resolution_comment,
        resolved_by_user_id=v.resolved_by_user_id,
        resolved_by_email=emails.get(v.resolved_by_user_id or ""),
        assignee_user_id=v.assignee_user_id,
        assignee_email=emails.get(v.assignee_user_id or ""),
        current_severity=v.current_severity,
        current_priority_score=v.current_priority_score,
        current_priority_tier=v.current_priority_tier,
        current_rule_id=v.current_rule_id,
        current_rule_name=v.current_rule_name,
        current_kind=v.current_kind,
        current_message=v.current_message,
        current_location=v.current_location,
        current_scan_id=v.current_scan_id,
        latest_finding_id=v.latest_finding_id,
        first_seen_at=v.first_seen_at,
        last_seen_at=v.last_seen_at,
        resolved_at=v.resolved_at,
        reopened_at=v.reopened_at,
        last_regression_state=v.last_regression_state,
        last_regression_scan_id=v.last_regression_scan_id,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


async def _get_vuln_or_404(project_id: str, vulnerability_id: str) -> Vulnerability:
    v = await Vulnerability.get(vulnerability_id)
    if not v or v.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vulnerability not found")
    return v


def _emails_for(rows: list[Vulnerability]) -> set[str]:
    ids: set[str] = set()
    for v in rows:
        if v.assignee_user_id:
            ids.add(v.assignee_user_id)
        if v.resolved_by_user_id:
            ids.add(v.resolved_by_user_id)
    return ids


# --- list + detail -------------------------------------------------------------------------


@router.get("/projects/{project_id}/vulnerabilities", response_model=Page)
async def list_vulnerabilities(
    project_id: str,
    status_filter: str | None = Query(None, alias="status"),
    severity: str | None = Query(None),
    kind: str | None = Query(None),
    repo: str | None = Query(None, description="project_repo_id, or the unlinked-bucket key"),
    assignee_user_id: str | None = Query(None),
    regression_state: str | None = Query(None),
    search: str | None = Query(None, description="matches rule name, message, or fingerprint"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = Query(_DEFAULT_SORT),
    user: User = Depends(get_current_user),
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    criteria: list = [Vulnerability.project_id == project_id]
    if status_filter:
        criteria.append(Vulnerability.status == status_filter)
    if severity:
        criteria.append(Vulnerability.current_severity == severity)
    if kind:
        criteria.append(Vulnerability.current_kind == kind)
    if repo:
        criteria.append(Vulnerability.repo_scope_key == repo)
    if assignee_user_id:
        criteria.append(Vulnerability.assignee_user_id == assignee_user_id)
    if regression_state:
        criteria.append(Vulnerability.last_regression_state == regression_state)
    if search:
        pattern = re.escape(search)
        criteria.append(
            {
                "$or": [
                    {"current_rule_name": {"$regex": pattern, "$options": "i"}},
                    {"current_message": {"$regex": pattern, "$options": "i"}},
                    {"fingerprint": {"$regex": pattern, "$options": "i"}},
                ]
            }
        )

    # Server-side paging + filtering -- never load-all-then-slice, per the project's scale
    # concerns (see routers/audit_logs.py's own admission that the in-memory approach doesn't
    # scale, which this deliberately does not repeat).
    query = Vulnerability.find(*criteria)
    total = await query.count()
    rows = (
        await query.sort(_sort_expr(sort))
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )

    emails = await _email_map(_emails_for(rows))
    return Page(items=[_to_out(v, emails) for v in rows], total=total, page=page, page_size=page_size)


@router.get(
    "/projects/{project_id}/vulnerabilities/{vulnerability_id}",
    response_model=VulnerabilityDetailResponse,
)
async def get_vulnerability(
    project_id: str, vulnerability_id: str, user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    vuln = await _get_vuln_or_404(project_id, vulnerability_id)

    # vulnerability_id-tagged findings are the real cross-scan history; the fingerprint fallback
    # only matters for findings ingested before reconcile_scan started stamping it.
    findings = await Finding.find(
        Finding.project_id == project_id, Finding.vulnerability_id == str(vuln.id)
    ).to_list()
    if not findings:
        findings = await Finding.find(
            Finding.project_id == project_id, Finding.fingerprint == vuln.fingerprint
        ).to_list()

    scan_oids = [PydanticObjectId(sid) for sid in {f.scan_id for f in findings} if PydanticObjectId.is_valid(sid)]
    scans_by_id = {str(s.id): s for s in await Scan.find(In(Scan.id, scan_oids)).to_list()} if scan_oids else {}

    observations = [
        VulnerabilityScanObservation(
            scan_id=f.scan_id,
            finding_id=str(f.id),
            scan_status=s.status,
            scan_type=s.scan_type,
            severity=f.severity,
            created_at=s.created_at,
            completed_at=s.completed_at,
        )
        for f in findings
        if (s := scans_by_id.get(f.scan_id)) is not None
    ]
    observations.sort(key=lambda o: o.created_at, reverse=True)

    logs = (
        await AuditLog.find(
            AuditLog.target_type == "vulnerability", AuditLog.target_id == str(vuln.id)
        )
        .sort("-created_at")
        .to_list()
    )
    emails = await _email_map(
        _emails_for([vuln]) | {log.actor_user_id for log in logs if log.actor_user_id}
    )
    activity = [
        VulnerabilityActivityEvent(
            action=log.action,
            actor_type=log.actor_type,
            actor_user_id=log.actor_user_id,
            actor_email=emails.get(log.actor_user_id or ""),
            metadata=log.metadata,
            created_at=log.created_at,
        )
        for log in logs
    ]

    base = _to_out(vuln, emails)
    return VulnerabilityDetailResponse(**base.model_dump(), observations=observations, activity=activity)


# --- transitions ----------------------------------------------------------------------------


@router.patch(
    "/projects/{project_id}/vulnerabilities/{vulnerability_id}/status",
    response_model=VulnerabilityOut,
)
async def update_vulnerability_status(
    project_id: str,
    vulnerability_id: str,
    payload: VulnerabilityStatusUpdateRequest,
    user: User = Depends(get_current_user),
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    vuln = await _get_vuln_or_404(project_id, vulnerability_id)

    now = datetime.now(timezone.utc)
    before = {
        "status": vuln.status,
        "resolution_reason": vuln.resolution_reason,
        "resolution_comment": vuln.resolution_comment,
    }

    if payload.status == "resolved":
        if not payload.resolution_reason:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "resolution_reason is required to resolve a vulnerability",
            )
        # A human hitting "resolved -> fixed" through this endpoint is always a manual claim --
        # the automatic "fixed" verdict comes only from reconcile_scan finding the fingerprint
        # gone, never from this route -- so scanner evidence is preferred over an unexplained
        # human assertion.
        if payload.resolution_reason == "fixed" and not (payload.resolution_comment or "").strip():
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "resolution_comment is required when manually marking a vulnerability fixed",
            )
        vuln.status = "resolved"
        vuln.resolution_reason = payload.resolution_reason
        vuln.resolution_comment = payload.resolution_comment
        vuln.resolved_at = now
        vuln.resolved_by_user_id = str(user.id)
    else:
        was_resolved = vuln.status == "resolved"
        vuln.status = payload.status
        if was_resolved:
            vuln.resolution_reason = None
            vuln.resolution_comment = None
            vuln.resolved_at = None
            vuln.resolved_by_user_id = None
            vuln.reopened_at = now
        # in_progress / open / accepted_risk: first_seen_at and assignee are left untouched --
        # this endpoint never writes them.

    vuln.updated_at = now
    await vuln.save()

    after = {
        "status": vuln.status,
        "resolution_reason": vuln.resolution_reason,
        "resolution_comment": vuln.resolution_comment,
    }
    changed = {k: {"before": before[k], "after": after[k]} for k in before if before[k] != after[k]}
    await audit_service.record(
        "Vulnerability Status Updated",
        actor_type="user",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="vulnerability",
        target_id=str(vuln.id),
        metadata=changed,
    )

    emails = await _email_map(_emails_for([vuln]))
    return _to_out(vuln, emails)


@router.patch(
    "/projects/{project_id}/vulnerabilities/{vulnerability_id}/assignment",
    response_model=VulnerabilityOut,
)
async def update_vulnerability_assignment(
    project_id: str,
    vulnerability_id: str,
    payload: VulnerabilityAssignmentUpdateRequest,
    user: User = Depends(get_current_user),
):
    await project_service.get_project_or_404(project_id)
    role = await project_service.require_member(project_id, user)
    vuln = await _get_vuln_or_404(project_id, vulnerability_id)
    target = payload.assignee_user_id

    if role not in ("owner", "admin") and target not in (None, str(user.id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Collaborators may only assign themselves")

    if target is not None:
        is_member = await ProjectMember.find_one(
            ProjectMember.project_id == project_id, ProjectMember.user_id == target
        )
        if not is_member:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Assignee is not a member of this project")

    before = vuln.assignee_user_id
    if before != target:
        vuln.assignee_user_id = target
        vuln.updated_at = datetime.now(timezone.utc)
        await vuln.save()
        await audit_service.record(
            "Vulnerability Assignment Updated",
            actor_type="user",
            actor_user_id=str(user.id),
            project_id=project_id,
            target_type="vulnerability",
            target_id=str(vuln.id),
            metadata={"assignee_user_id": {"before": before, "after": target}},
        )

    emails = await _email_map(_emails_for([vuln]))
    return _to_out(vuln, emails)


# --- per-scan regression read (advisory state stamped by reconcile_scan) -------------------


@router.get(
    "/projects/{project_id}/scans/{scan_id}/regression",
    response_model=ScanRegressionResponse,
)
async def get_scan_regression(
    project_id: str, scan_id: str, user: User = Depends(get_current_user)
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    scan = await Scan.get(scan_id)
    if not scan or scan.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")

    repos = await project_repo_service.list_repos(project_id)
    resolve = stats_svc.repo_key_resolver(repos)
    scope_key = resolve(scan)

    completed = (
        await Scan.find(Scan.project_id == project_id, Scan.status == "completed")
        .sort(-Scan.created_at)
        .to_list()
    )
    scope_scans = [s for s in completed if resolve(s) == scope_key]
    is_latest = bool(scope_scans) and str(scope_scans[0].id) == scan_id
    try:
        self_index = next(i for i, s in enumerate(scope_scans) if str(s.id) == scan_id)
        baseline = scope_scans[self_index + 1] if self_index + 1 < len(scope_scans) else None
    except StopIteration:
        # This scan itself isn't in the completed list (still running, failed, or reaped) --
        # the newest completed scan in scope is still the right thing to compare against.
        baseline = scope_scans[0] if scope_scans else None

    # last_regression_state/scan_id were stamped once, at reconcile time -- this is a read of
    # that bookkeeping, never a recomputation.
    rows = await Vulnerability.find(
        Vulnerability.project_id == project_id, Vulnerability.last_regression_scan_id == scan_id
    ).to_list()

    emails = await _email_map(_emails_for(rows))
    buckets: dict[str, list[VulnerabilityOut]] = {"new": [], "unchanged": [], "reopened": [], "fixed": []}
    counts: dict[str, int] = {"new": 0, "unchanged": 0, "reopened": 0, "fixed": 0}
    for v in rows:
        state = v.last_regression_state
        if state not in buckets:
            continue
        counts[state] += 1
        # `count` is the true total; `items` is a bounded preview. The first scan of a large
        # repo puts every finding in "new", and serializing thousands of full rows into the
        # KPI strip's response would dwarf the page that renders it. The work queue
        # (?regression_state=) is the paged view for reading past the preview.
        if len(buckets[state]) < _REGRESSION_PREVIEW_LIMIT:
            buckets[state].append(_to_out(v, emails))

    return ScanRegressionResponse(
        scan_id=scan_id,
        baseline_scan_id=str(baseline.id) if baseline else None,
        has_baseline=baseline is not None,
        is_latest_for_scope=is_latest,
        new=RegressionBucket(count=counts["new"], items=buckets["new"]),
        unchanged=RegressionBucket(count=counts["unchanged"], items=buckets["unchanged"]),
        reopened=RegressionBucket(count=counts["reopened"], items=buckets["reopened"]),
        fixed=RegressionBucket(count=counts["fixed"], items=buckets["fixed"]),
    )

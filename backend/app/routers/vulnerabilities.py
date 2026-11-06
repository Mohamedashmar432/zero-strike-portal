"""Vulnerability lifecycle HTTP surface: the work-queue list/detail, human status/assignment
transitions, and the per-scan regression read. Stage 1 (app.services.vulnerability_service)
is the only writer of current_*/regression fields via reconcile_scan -- this router only ever
writes the human-triage fields (status, resolution, assignee) it owns outright, and never
touches reconcile_scan's own bookkeeping (first_seen_at, last_regression_*, current_*).
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_current_user
from app.models.audit_log import AuditLog
from app.models.finding import Finding
from app.models.scan import Scan
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.schemas.common import Page
from app.schemas.vulnerability import (
    FindingReviewOut,
    FixedViaPullRequest,
    RegressionBucket,
    ScanRegressionResponse,
    VulnerabilityActivityEvent,
    VulnerabilityAssignmentUpdateRequest,
    VulnerabilityBulkItemResult,
    VulnerabilityBulkRequest,
    VulnerabilityBulkResponse,
    VulnerabilityDetailResponse,
    VulnerabilityCounts,
    VulnerabilityOut,
    VulnerabilityScanObservation,
    VulnerabilityStatusUpdateRequest,
    VulnerabilitySummaryResponse,
)
from app.services import (
    pr_status_service,
    project_repo_service,
    project_service,
    scan_engine_service,
    vulnerability_service,
    vulnerability_query_service as query_svc,
    vulnerability_triage_service,
)
from app.services import project_stats_service as stats_svc

router = APIRouter(tags=["vulnerabilities"])

# How many rows per regression bucket the scan-detail response carries. The bucket `count` is
# always the true total -- this only bounds the inlined preview, since the first scan of a large
# repo classifies every finding as "new" and would otherwise serialize thousands of rows.
_REGRESSION_PREVIEW_LIMIT = 25


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
        review=_review_out(v, emails),
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
        fix_status=vulnerability_service.derive_fix_status(v.status, v.resolution_reason, v.reopened_at),
        first_seen_commit=v.first_seen_commit,
        first_seen_branch=v.first_seen_branch,
        first_seen_scan_id=v.first_seen_scan_id,
        last_seen_commit=v.last_seen_commit,
        fixed_commit=v.fixed_commit,
        fixed_branch=v.fixed_branch,
        fixed_scan_id=v.fixed_scan_id,
        reopened_commit=v.reopened_commit,
        last_regression_state=v.last_regression_state,
        last_regression_scan_id=v.last_regression_scan_id,
        created_at=v.created_at,
        updated_at=v.updated_at,
    )


def _review_out(v: Vulnerability, emails: dict[str, str]) -> FindingReviewOut | None:
    r = v.review
    if r is None:
        return None
    return FindingReviewOut(
        **r.model_dump(),
        requested_by_email=emails.get(r.requested_by_user_id),
        reviewed_by_email=emails.get(r.reviewed_by_user_id or ""),
    )


async def _get_vuln_or_404(project_id: str, vulnerability_id: str) -> Vulnerability:
    v = await Vulnerability.get(vulnerability_id)
    if not v or v.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vulnerability not found")
    return v


async def _scans_by_id(findings: list[Finding]) -> dict[str, Scan]:
    oids = [PydanticObjectId(sid) for sid in {f.scan_id for f in findings} if PydanticObjectId.is_valid(sid)]
    return {str(s.id): s for s in await Scan.find(In(Scan.id, oids)).to_list()} if oids else {}


def _emails_for(rows: list[Vulnerability]) -> set[str]:
    ids: set[str] = set()
    for v in rows:
        if v.assignee_user_id:
            ids.add(v.assignee_user_id)
        if v.resolved_by_user_id:
            ids.add(v.resolved_by_user_id)
        if v.review:
            ids.add(v.review.requested_by_user_id)
            if v.review.reviewed_by_user_id:
                ids.add(v.review.reviewed_by_user_id)
    return ids


# --- list + detail -------------------------------------------------------------------------


def _filters(
    status_filter: str | None = Query(None, alias="status", description="comma-separated; includes false_positive"),
    fix_status: Literal["open", "reopened", "fixed", "dismissed"] | None = Query(None),
    severity: str | None = Query(None, description="comma-separated"),
    kind: str | None = Query(None, description="comma-separated: sast,secret,sca,config"),
    repo: str | None = Query(None, description="comma-separated project_repo_id / unlinked-bucket keys"),
    rule_id: str | None = Query(None, description="comma-separated rule ids"),
    path: str | None = Query(None, description="substring of the file path"),
    assignee: str | None = Query(None, description="comma-separated user ids; __none__ = unassigned"),
    assignee_user_id: str | None = Query(None, description="legacy single-user form of `assignee`"),
    review_state: str | None = Query(None, description="comma-separated: none,pending,accepted,rejected,revoked"),
    review_kind: str | None = Query(None, description="comma-separated: false_positive,accepted_risk"),
    age: str | None = Query(None, description="comma-separated: 7d,30d,90d (first seen within), 90d+ (older)"),
    regression_state: str | None = Query(None),
    search: str | None = Query(None, description="matches rule name, message, or fingerprint"),
) -> query_svc.VulnFilters:
    """The filters the list and the facet counts share. Absent / empty = no filter."""
    f: query_svc.VulnFilters = {
        "status": query_svc.csv(status_filter),
        "fix_status": fix_status,
        "severity": query_svc.csv(severity),
        "kind": query_svc.csv(kind),
        "repo": query_svc.csv(repo),
        "rule_id": query_svc.csv(rule_id),
        "path": (path or "").strip(),
        "assignee": query_svc.csv(assignee) + ([assignee_user_id] if assignee_user_id else []),
        "review_state": [x for x in query_svc.csv(review_state) if x in query_svc.REVIEW_STATES],
        "review_kind": query_svc.csv(review_kind),
        "age": [x for x in query_svc.csv(age) if x in query_svc.AGE_VALUES],
        "regression_state": regression_state,
        "search": (search or "").strip(),
    }
    return {k: v for k, v in f.items() if v}


@router.get("/projects/{project_id}/vulnerabilities", response_model=Page)
async def list_vulnerabilities(
    project_id: str,
    filters: query_svc.VulnFilters = Depends(_filters),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    sort: str = Query(query_svc.DEFAULT_SORT, description="[-]last_seen_at|first_seen_at|priority|severity|rule|file"),
    user: User = Depends(get_current_user),
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    criteria = query_svc.clauses(project_id, filters, await scan_engine_service.retired_rule_ids())

    # Server-side paging + filtering -- never load-all-then-slice, per the project's scale
    # concerns (see routers/audit_logs.py's own admission that the in-memory approach doesn't
    # scale, which this deliberately does not repeat).
    total = await Vulnerability.find(criteria).count()
    skip = (page - 1) * page_size
    by_severity, most_severe_first = query_svc.is_severity_sort(sort)
    if by_severity:
        rows = await query_svc.severity_ordered_page(
            criteria, most_severe_first=most_severe_first, skip=skip, limit=page_size
        )
    else:
        rows = (
            await Vulnerability.find(criteria)
            .sort(query_svc.sort_expr(sort) or query_svc.sort_expr(query_svc.DEFAULT_SORT))
            .skip(skip)
            .limit(page_size)
            .to_list()
        )

    emails = await _email_map(_emails_for(rows))
    return Page(items=[_to_out(v, emails) for v in rows], total=total, page=page, page_size=page_size)


@router.get("/projects/{project_id}/vulnerabilities/facets")
async def get_vulnerability_facets(
    project_id: str,
    filters: query_svc.VulnFilters = Depends(_filters),
    user: User = Depends(get_current_user),
):
    """Counts per filter value, each computed with every *other* filter applied (so choosing High does not
    zero out the other severities). Same query params as the list. Only non-zero values are present.
    Registered before the `{vulnerability_id}` route so "facets" is never parsed as an id."""
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    return await query_svc.facets(
        project_id, filters, await scan_engine_service.retired_rule_ids(), _email_map
    )


@router.post("/projects/{project_id}/vulnerabilities/bulk", response_model=VulnerabilityBulkResponse)
async def bulk_update_vulnerabilities(
    project_id: str, payload: VulnerabilityBulkRequest, user: User = Depends(get_current_user)
):
    """Apply one assignment or status change to up to 100 vulnerabilities. Every item goes through the same
    rules and audit as the single routes, so a status that needs review becomes a review request, and an
    item that is refused reports why without stopping the rest."""
    await project_service.get_project_or_404(project_id)
    role = await project_service.require_member(project_id, user)

    results: list[VulnerabilityBulkItemResult] = []
    for vid in dict.fromkeys(payload.ids):
        try:
            if not PydanticObjectId.is_valid(vid):
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Vulnerability not found")
            vuln = await _get_vuln_or_404(project_id, vid)
            if payload.action == "assign":
                vuln = await vulnerability_triage_service.apply_assignment(
                    vuln, payload.assignee_user_id, user, role
                )
            else:
                vuln = await vulnerability_triage_service.apply_status_change(
                    vuln, payload.status, payload.resolution_reason, payload.resolution_comment, user
                )
        except HTTPException as e:
            results.append(VulnerabilityBulkItemResult(id=vid, ok=False, detail=str(e.detail)))
            continue
        results.append(
            VulnerabilityBulkItemResult(
                id=vid,
                ok=True,
                status=vuln.status,
                review_status=vuln.review.status if vuln.review else None,
                assignee_user_id=vuln.assignee_user_id,
            )
        )
    succeeded = sum(1 for r in results if r.ok)
    return VulnerabilityBulkResponse(results=results, succeeded=succeeded, failed=len(results) - succeeded)


@router.get("/projects/{project_id}/vulnerabilities/summary", response_model=VulnerabilitySummaryResponse)
async def get_vulnerability_summary(
    project_id: str,
    repo: str | None = Query(None, description="project_repo_id, or the unlinked-bucket key"),
    user: User = Depends(get_current_user),
):
    """Counts by lifecycle bucket, overall and per repo. Registered before the `{vulnerability_id}`
    route so "summary" is never parsed as an id."""
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    match: dict = {"project_id": project_id}
    if repo:
        match["repo_scope_key"] = repo
    retired = await scan_engine_service.retired_rule_ids()
    if retired:
        match["current_rule_id"] = {"$nin": sorted(retired)}
    groups =await Vulnerability.get_pymongo_collection().aggregate(
        [
            {"$match": match},
            {
                "$group": {
                    "_id": {
                        "repo": "$repo_scope_key",
                        "status": "$status",
                        "reason": "$resolution_reason",
                        "reopened": {"$cond": [{"$ifNull": ["$reopened_at", False]}, True, False]},
                    },
                    "n": {"$sum": 1},
                }
            },
        ]
    ).to_list(length=None)

    total = VulnerabilityCounts()
    by_repo: dict[str, VulnerabilityCounts] = {}
    for g in groups:
        k = g["_id"]
        if k["status"] == "in_progress":
            bucket = "reopened" if k["reopened"] else "in_progress"
        else:
            bucket = vulnerability_service.derive_fix_status(
                k["status"], k["reason"], datetime.now(timezone.utc) if k["reopened"] else None
            )
        for counts in (total, by_repo.setdefault(k["repo"], VulnerabilityCounts())):
            setattr(counts, bucket, getattr(counts, bucket) + g["n"])
    return VulnerabilitySummaryResponse(**total.model_dump(), by_repo=by_repo)


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
        # repo_scope_key is half this vulnerability's identity (the same fingerprint in another
        # repo is a different vulnerability, never this one's history) -- so the legacy fallback
        # has to filter by scope too, not just fingerprint, using the same resolver reconcile_scan
        # used to assign repo_scope_key in the first place.
        legacy = await Finding.find(
            Finding.project_id == project_id, Finding.fingerprint == vuln.fingerprint
        ).to_list()
        resolve = stats_svc.repo_key_resolver(await project_repo_service.list_repos(project_id))
        legacy_scans_by_id = await _scans_by_id(legacy)
        findings = [
            f
            for f in legacy
            if (s := legacy_scans_by_id.get(f.scan_id)) is not None and resolve(s) == vuln.repo_scope_key
        ]

    scans_by_id = await _scans_by_id(findings)

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
    fixed_via_pr = None
    if base.fix_status == "fixed":
        merged = await pr_status_service.merged_pr_for_findings([str(f.id) for f in findings])
        if merged is not None:
            fixed_via_pr = FixedViaPullRequest(
                pr_number=merged.pr_number,
                pr_url=merged.pr_url,
                pr_provider=merged.pr_provider,
                merged_at=merged.pr_merged_at,
                merge_commit=merged.pr_merge_commit,
            )
    return VulnerabilityDetailResponse(
        **base.model_dump(), observations=observations, activity=activity, fixed_via_pr=fixed_via_pr
    )


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

    # A verdict that would stop the finding blocking CI is a *request* for a portal admin to review
    # (docs/FINDING_REVIEW.md): false positive on code findings, accepted risk on any finding. The
    # finding keeps its status, and keeps blocking, until the review is accepted.
    vuln = await vulnerability_triage_service.apply_status_change(
        vuln, payload.status, payload.resolution_reason, payload.resolution_comment, user
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
    vuln = await vulnerability_triage_service.apply_assignment(vuln, payload.assignee_user_id, user, role)

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
        commit=scan.git_commit,
        branch=scan.branch,
        baseline_commit=baseline.git_commit if baseline else None,
        baseline_branch=baseline.branch if baseline else None,
        baseline_branch_mismatch=bool(
            baseline and baseline.branch and scan.branch and baseline.branch != scan.branch
        ),
        scanner_version_changed=bool(
            baseline
            and baseline.scanner_version
            and scan.scanner_version
            and baseline.scanner_version != scan.scanner_version
        ),
        new=RegressionBucket(count=counts["new"], items=buckets["new"]),
        unchanged=RegressionBucket(count=counts["unchanged"], items=buckets["unchanged"]),
        reopened=RegressionBucket(count=counts["reopened"], items=buckets["reopened"]),
        fixed=RegressionBucket(count=counts["fixed"], items=buckets["fixed"]),
    )

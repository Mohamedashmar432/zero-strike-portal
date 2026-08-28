"""Per-scan AI Auto-Fix quota: read usage, request more headroom, and (admin) decide.

Two principals, deliberately split the way scans/ and scanner_scans/ are:
  * member routes hang off /scans/{scan_id}/... and are gated by project membership;
  * the review queue lives under /admin/... behind require_admin.
A member can therefore never see another team's requests, and only an admin can
grant headroom — which is what actually authorises additional LLM spend.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_current_user, require_admin
from app.models.auto_fix_quota import AutoFixQuotaRequest
from app.models.project import Project
from app.models.user import User
from app.schemas.auto_fix_quota import (
    AutoFixQuotaRequestCreate,
    AutoFixQuotaRequestDecision,
    AutoFixQuotaRequestListResponse,
    AutoFixQuotaRequestOut,
    ScanAutoFixQuotaResponse,
)
from app.services import (
    audit_service,
    auto_fix_quota_service,
    notification_service,
    project_service,
    scan_service,
)

router = APIRouter(tags=["auto-fix-quota"])


async def _resolve_labels(reqs: list[AutoFixQuotaRequest]) -> list[AutoFixQuotaRequestOut]:
    """Batch-resolve project names and user emails so the list is one query per collection."""
    project_ids = {r.project_id for r in reqs}
    user_ids = {r.requested_by for r in reqs} | {r.decided_by for r in reqs if r.decided_by}

    projects = (
        {str(p.id): p.name for p in await Project.find({"_id": {"$in": list(project_ids)}}).to_list()}
        if project_ids
        else {}
    )
    # Project ids are stored as strings; Beanie needs PydanticObjectId for _id queries, so
    # fall back to per-id gets when the bulk form finds nothing usable.
    if project_ids and not projects:
        for pid in project_ids:
            p = await Project.get(pid)
            if p:
                projects[pid] = p.name

    users: dict[str, str] = {}
    for uid in user_ids:
        u = await User.get(uid)
        if u:
            users[uid] = u.email

    return [
        AutoFixQuotaRequestOut(
            id=str(r.id),
            scan_id=r.scan_id,
            project_id=r.project_id,
            project_name=projects.get(r.project_id),
            requested_by=r.requested_by,
            requested_by_email=users.get(r.requested_by),
            requested_additional=r.requested_additional,
            reason=r.reason,
            status=r.status,
            granted_additional=r.granted_additional,
            decision_note=r.decision_note,
            decided_by=r.decided_by,
            decided_by_email=users.get(r.decided_by) if r.decided_by else None,
            decided_at=r.decided_at,
            created_at=r.created_at,
        )
        for r in reqs
    ]


# --- member surface ----------------------------------------------------------


@router.get("/scans/{scan_id}/auto-fix/quota", response_model=ScanAutoFixQuotaResponse)
async def get_scan_auto_fix_quota(scan_id: str, user: User = Depends(get_current_user)):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    return ScanAutoFixQuotaResponse(
        **await auto_fix_quota_service.get_usage(scan_id, scan.project_id)
    )


@router.get(
    "/scans/{scan_id}/auto-fix/quota/requests", response_model=AutoFixQuotaRequestListResponse
)
async def list_scan_quota_requests(scan_id: str, user: User = Depends(get_current_user)):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    reqs = await AutoFixQuotaRequest.find(AutoFixQuotaRequest.scan_id == scan_id).sort("-created_at").to_list()
    items = await _resolve_labels(reqs)
    return AutoFixQuotaRequestListResponse(
        items=items, pending_count=sum(1 for r in reqs if r.status == "pending")
    )


@router.post(
    "/scans/{scan_id}/auto-fix/quota/requests",
    response_model=AutoFixQuotaRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_scan_quota_request(
    scan_id: str,
    payload: AutoFixQuotaRequestCreate,
    user: User = Depends(get_current_user),
):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    req = await auto_fix_quota_service.create_request(
        scan_id=scan_id,
        project_id=scan.project_id,
        requested_by=str(user.id),
        requested_additional=payload.requested_additional,
        reason=payload.reason,
    )
    await audit_service.record(
        "Auto-Fix Quota Requested",
        actor_user_id=str(user.id),
        project_id=scan.project_id,
        target_type="scan",
        target_id=scan_id,
        metadata={"requested_additional": payload.requested_additional},
    )
    # Admin audience: a request nobody sees is a request nobody decides.
    await notification_service.notify(
        "autofix.quota_requested",
        project_id=scan.project_id,
        title=f"Auto-fix allowance requested (+{payload.requested_additional})",
        body=payload.reason,
        link="/admin/auto-fix-requests",
        severity="warning",
    )
    return (await _resolve_labels([req]))[0]


# --- admin review queue ------------------------------------------------------


@router.get("/admin/auto-fix-quota/requests", response_model=AutoFixQuotaRequestListResponse)
async def list_all_quota_requests(
    status_filter: str | None = Query(default=None, alias="status"),
    user: User = Depends(require_admin),
):
    if status_filter not in (None, "pending", "approved", "rejected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status filter")
    reqs = await auto_fix_quota_service.list_requests(status_filter=status_filter)
    # Pending count is always the full queue depth, not the filtered view, so the
    # nav badge stays correct while an admin is browsing "approved".
    pending = await AutoFixQuotaRequest.find(AutoFixQuotaRequest.status == "pending").count()
    return AutoFixQuotaRequestListResponse(items=await _resolve_labels(reqs), pending_count=pending)


@router.post(
    "/admin/auto-fix-quota/requests/{request_id}/decide", response_model=AutoFixQuotaRequestOut
)
async def decide_quota_request(
    request_id: str,
    payload: AutoFixQuotaRequestDecision,
    user: User = Depends(require_admin),
):
    req = await auto_fix_quota_service.decide_request(
        request_id=request_id,
        approve=payload.approve,
        decided_by=str(user.id),
        granted_additional=payload.granted_additional,
        decision_note=payload.decision_note,
    )
    await audit_service.record(
        "Auto-Fix Quota Approved" if payload.approve else "Auto-Fix Quota Rejected",
        actor_user_id=str(user.id),
        project_id=req.project_id,
        target_type="scan",
        target_id=req.scan_id,
        metadata={
            "request_id": request_id,
            "requested_additional": req.requested_additional,
            "granted_additional": req.granted_additional,
        },
    )
    return (await _resolve_labels([req]))[0]

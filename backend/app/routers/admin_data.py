"""Portal data management -- what a portal admin needs to clear out test/demo data.

Router-level require_admin (as in admin_ai_analytics): nothing here is meaningful to a
non-admin, since every operation spans projects the caller may not be a member of.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core.deps import require_admin
from app.models.user import User
from app.schemas.data_management import (
    DataStatsResponse,
    PurgeRequest,
    PurgeResponse,
    ReapResponse,
)
from app.services import audit_service, data_management_service, scan_queue_service

router = APIRouter(prefix="/admin/data", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/stats", response_model=DataStatsResponse)
async def get_data_stats(project_id: str | None = Query(None, description="Scope counts to one project")):
    return DataStatsResponse(
        project_id=project_id,
        categories=await data_management_service.get_stats(project_id),
    )


@router.post("/purge", response_model=PurgeResponse)
async def purge_data(payload: PurgeRequest, request: Request, admin: User = Depends(require_admin)):
    known = {c.key for c in data_management_service.CATEGORIES}
    unknown = sorted(set(payload.categories) - known)
    if unknown:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown categories: {', '.join(unknown)}")

    expanded = data_management_service.expand(payload.categories)
    deleted = await data_management_service.purge(payload.categories, project_id=payload.project_id)

    # Recorded *after* the wipe on purpose -- purging the audit log would otherwise erase
    # the record of the purge itself.
    await audit_service.record(
        "admin.data.purge",
        actor_user_id=str(admin.id),
        project_id=payload.project_id,
        target_type="portal_data",
        metadata={"categories": expanded, "deleted": deleted},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return PurgeResponse(
        categories=expanded, deleted=deleted, total_deleted=sum(deleted.values())
    )


@router.post("/reap-stuck-scans", response_model=ReapResponse)
async def reap_stuck_scans():
    """Manually run the reaper the queue poll loop runs on a timer -- for when a scan is
    wedged in `running` and the admin does not want to wait out the timeout window."""
    await scan_queue_service.reap_stuck_scans()
    return ReapResponse(reaped=True)

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status

from app.core.deps import require_admin
from app.models.scan import ScanStatus, ScanType
from app.models.user import User
from app.schemas.project import CloudScanQuota
from app.schemas.project_insights import (
    CloudScanLimitRequest,
    ProjectActivityResponse,
    ProjectInsightsResponse,
    ScanRequestsResponse,
)
from app.services import (
    audit_service,
    cloud_scan_quota_service,
    project_insights_service,
    workspace_settings_service,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/project-insights", response_model=ProjectInsightsResponse)
async def get_project_insights(since: datetime | None = Query(None), until: datetime | None = Query(None)):
    since, until = project_insights_service.window(since, until)
    return await project_insights_service.get_insights(since, until)


@router.get("/project-insights/projects/{project_id}/activity", response_model=ProjectActivityResponse)
async def get_project_activity(
    project_id: str,
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=200),
):
    project = await workspace_settings_service.load_project(project_id)
    if project is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Project not found")
    since, until = project_insights_service.window(since, until)
    return await project_insights_service.project_activity(project, since, until, limit)


@router.get("/project-insights/requests", response_model=ScanRequestsResponse)
async def list_scan_requests(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    project_id: str | None = Query(None),
    scan_type: ScanType | None = Query(None),
    status: ScanStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    since, until = project_insights_service.window(since, until)
    return await project_insights_service.list_requests(
        since, until, project_id=project_id, scan_type=scan_type, scan_status=status, limit=limit, offset=offset
    )


@router.put("/projects/{project_id}/cloud-scan-limit", response_model=CloudScanQuota)
async def set_cloud_scan_limit(
    project_id: str, payload: CloudScanLimitRequest, admin: User = Depends(require_admin)
):
    project = await workspace_settings_service.load_project(project_id)
    if project is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Project not found")
    old = project.cloud_scan_monthly_limit
    project.cloud_scan_monthly_limit = payload.monthly_limit
    project.updated_at = datetime.now(timezone.utc)
    await project.save()
    await audit_service.record(
        "Cloud Scan Limit Changed",
        actor_user_id=str(admin.id),
        project_id=project_id,
        target_type="project",
        target_id=project_id,
        metadata={"old": old, "new": payload.monthly_limit},
    )
    return await cloud_scan_quota_service.usage(project)

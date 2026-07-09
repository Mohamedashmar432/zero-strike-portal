from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import settings
from app.core.deps import get_current_user
from app.models.scan import Scan
from app.models.user import User
from app.schemas.common import Page
from app.schemas.scan import ScanCreateRequest, ScanMockCompleteRequest, ScanResponse
from app.services import audit_service, project_service, scan_service

router = APIRouter(tags=["scans"])


def _to_response(scan: Scan) -> ScanResponse:
    return ScanResponse(
        id=str(scan.id),
        project_id=scan.project_id,
        scan_type=scan.scan_type,
        triggered_by=scan.triggered_by,
        status=scan.status,
        api_key_id=scan.api_key_id,
        scanner_version=scan.scanner_version,
        hostname=scan.hostname,
        git_commit=scan.git_commit,
        branch=scan.branch,
        scan_label=scan.scan_label,
        repo_url=scan.repo_url,
        ci_provider=scan.ci_provider,
        created_by=scan.created_by,
        started_at=scan.started_at,
        completed_at=scan.completed_at,
        error_message=scan.error_message,
        created_at=scan.created_at,
        updated_at=scan.updated_at,
    )


@router.post("/projects/{project_id}/scans", response_model=ScanResponse, status_code=status.HTTP_201_CREATED)
async def create_scan(project_id: str, payload: ScanCreateRequest, user: User = Depends(get_current_user)):
    project = await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Project is archived")

    now = datetime.now(timezone.utc)
    scan = Scan(
        project_id=project_id,
        scan_type=payload.scan_type,
        triggered_by="manual",
        scan_label=payload.scan_label,
        repo_url=payload.repo_url,
        ci_provider=payload.ci_provider,
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await scan.insert()
    await scan_service.increment_scan_counter(project)
    await audit_service.record(
        "Scan Created",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="scan",
        target_id=str(scan.id),
        metadata={"scan_type": scan.scan_type, "scan_label": scan.scan_label},
    )
    return _to_response(scan)


@router.get("/projects/{project_id}/scans", response_model=Page)
async def list_scans(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    scan_type: str | None = Query(None),
    user: User = Depends(get_current_user),
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    criteria = [Scan.project_id == project_id]
    if status_filter:
        criteria.append(Scan.status == status_filter)
    if scan_type:
        criteria.append(Scan.scan_type == scan_type)

    query = Scan.find(*criteria)
    total = await query.count()
    scans = await query.sort("-created_at").skip((page - 1) * page_size).limit(page_size).to_list()
    return Page(items=[_to_response(s) for s in scans], total=total, page=page, page_size=page_size)


@router.get("/scans/{scan_id}", response_model=ScanResponse)
async def get_scan(scan_id: str, user: User = Depends(get_current_user)):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    return _to_response(scan)


@router.post("/scans/{scan_id}/_mock-complete", response_model=ScanResponse)
async def mock_complete_scan(
    scan_id: str, payload: ScanMockCompleteRequest, user: User = Depends(get_current_user)
):
    """TEMPORARY: demo-only, superseded by real scan-status transitions in Sprint 3."""
    if not settings.enable_mock_scan_endpoints:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)

    now = datetime.now(timezone.utc)
    if scan.started_at is None:
        scan.started_at = now
    scan.status = payload.status
    scan.completed_at = now
    scan.error_message = payload.error_message if payload.status == "failed" else None
    scan.updated_at = now
    await scan.save()
    await audit_service.record(
        "Scan Mock-Completed",
        actor_user_id=str(user.id),
        project_id=scan.project_id,
        target_type="scan",
        target_id=str(scan.id),
        metadata={"status": scan.status},
    )
    return _to_response(scan)

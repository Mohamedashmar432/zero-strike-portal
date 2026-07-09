"""Scanner-facing endpoints, authenticated by API key (not JWT).

These implement the exact REST contract the Go scanner's internal/portal client
calls. Kept in a separate router from the JWT-authed scans.py so the two auth
schemes never share a handler: every handler here depends on get_api_key_context
and receives an ApiKeyContext (a project scope), never a User.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pydantic import ValidationError

from app.core.deps import ApiKeyContext, get_api_key_context
from app.models.report import Report
from app.models.scan import Scan
from app.schemas.report import GoReportIn
from app.schemas.scan import ScannerCreateScanRequest, ScannerCreateScanResponse, ScannerStatusUpdateRequest
from app.services import audit_service, project_service, report_ingestion_service, scan_service
from app.storage import artifact_store

router = APIRouter(tags=["scanner"])


async def _owned_scan(scan_id: str, ctx: ApiKeyContext) -> Scan:
    scan = await scan_service.get_scan_or_404(scan_id)
    if scan.project_id != ctx.project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan


@router.post("/scans", response_model=ScannerCreateScanResponse, status_code=status.HTTP_201_CREATED)
async def scanner_create_scan(
    payload: ScannerCreateScanRequest, ctx: ApiKeyContext = Depends(get_api_key_context)
):
    if payload.project_id != ctx.project_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API key does not grant access to this project")
    project = await project_service.get_project_or_404(payload.project_id)
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Project is archived")

    now = datetime.now(timezone.utc)
    scan = Scan(
        project_id=payload.project_id,
        api_key_id=ctx.key_id,
        scan_type="local",
        triggered_by="cli",
        status="pending",
        scanner_version=payload.scanner_version,
        hostname=payload.hostname,
        git_commit=payload.git_commit,
        branch=payload.branch,
        scan_label=payload.scan_label,
        created_at=now,
        updated_at=now,
    )
    await scan.insert()
    await scan_service.increment_scan_counter(project)
    await audit_service.record(
        "Scan Created",
        actor_type="api_key",
        project_id=payload.project_id,
        target_type="scan",
        target_id=str(scan.id),
        metadata={"scanner_version": payload.scanner_version or "", "scan_label": payload.scan_label or ""},
    )
    return ScannerCreateScanResponse(scan_id=str(scan.id), status="pending")


@router.post("/scans/{scan_id}/upload/json")
async def upload_json(scan_id: str, request: Request, ctx: ApiKeyContext = Depends(get_api_key_context)):
    scan = await _owned_scan(scan_id, ctx)
    raw = await request.body()
    try:
        report = GoReportIn.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "Invalid scanner report JSON")

    json_path = artifact_store.write_json(scan.project_id, scan_id, raw)
    count = await report_ingestion_service.ingest(scan, report, json_path)
    await audit_service.record(
        "Scan Report Uploaded",
        actor_type="api_key",
        project_id=scan.project_id,
        target_type="scan",
        target_id=scan_id,
        metadata={"findings": count},
    )
    return {"scan_id": scan_id, "status": "completed", "findings": count}


@router.post("/scans/{scan_id}/upload/html")
async def upload_html(
    scan_id: str, file: UploadFile, ctx: ApiKeyContext = Depends(get_api_key_context)
):
    scan = await _owned_scan(scan_id, ctx)
    data = await file.read()
    html_path = artifact_store.write_html(scan.project_id, scan_id, data)
    report = await Report.find_one(Report.scan_id == scan_id)
    if report:
        report.html_path = html_path
        report.html_uploaded_at = datetime.now(timezone.utc)
        await report.save()
    return {"status": "ok"}


@router.put("/scans/{scan_id}/status")
async def update_status(
    scan_id: str, payload: ScannerStatusUpdateRequest, ctx: ApiKeyContext = Depends(get_api_key_context)
):
    scan = await _owned_scan(scan_id, ctx)
    now = datetime.now(timezone.utc)
    scan.status = payload.status
    scan.error_message = payload.error_message
    if payload.status in ("completed", "failed"):
        scan.completed_at = now
    scan.updated_at = now
    await scan.save()
    await audit_service.record(
        "Scan Status Updated",
        actor_type="api_key",
        project_id=scan.project_id,
        target_type="scan",
        target_id=scan_id,
        metadata={"status": payload.status},
    )
    return {"scan_id": scan_id, "status": scan.status}

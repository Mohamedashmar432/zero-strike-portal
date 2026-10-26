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
from app.models.project_repo import ProjectRepo
from app.models.report import Report
from app.models.scan import Scan
from app.schemas.report import GoReportIn
from app.schemas.scan import ScannerCreateScanRequest, ScannerCreateScanResponse, ScannerStatusUpdateRequest
from app.services import (
    audit_service,
    finding_review_service,
    project_repo_service,
    project_service,
    report_ingestion_service,
    scan_service,
)
from app.services import project_stats_service as stats_svc

router = APIRouter(tags=["scanner"])


async def _owned_scan(scan_id: str, ctx: ApiKeyContext) -> Scan:
    scan = await scan_service.get_scan_or_404(scan_id)
    if scan.project_id != ctx.project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan


async def _reject_foreign_repo(repo_url: str | None, ctx: ApiKeyContext, project_name: str) -> None:
    """Refuse a scan whose repo demonstrably belongs to another project.

    The key alone picks the project, so two pipelines with swapped keys would each file their report
    under the other's project and nothing would look wrong. A repo "belongs" to a project when it is
    connected there or that project has scanned it before. This project's own claim always wins, so a
    repo legitimately shared by two projects is unblocked by connecting it to both. Unknown repos and
    scans with no repo_url (older scanners) pass: there is nothing to compare against."""
    if not repo_url:
        return
    if await project_repo_service.find_repo_by_url(ctx.project_id, repo_url):
        return
    match = project_repo_service.repo_url_regex(repo_url)
    if await Scan.find_one({"project_id": ctx.project_id, "repo_url": match}):
        return
    other = {"project_id": {"$ne": ctx.project_id}}
    if not (
        await ProjectRepo.find_one({**other, "clone_url": match})
        or await Scan.find_one({**other, "repo_url": match})
    ):
        return
    await audit_service.record(
        "Scan Rejected",
        actor_type="api_key",
        project_id=ctx.project_id,
        target_type="api_key",
        target_id=ctx.key_id,
        metadata={"reason": "repo_belongs_to_another_project", "repo_url": repo_url},
    )
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        f"Project mismatch: this API key belongs to project '{project_name}', but repository "
        f"{repo_url} belongs to a different project. The pipeline is likely using another project's "
        f"API key — set the key generated for this repository's project. If the repository really "
        f"belongs to '{project_name}', connect it to that project in the portal, then re-run.",
    )


@router.post("/scans", response_model=ScannerCreateScanResponse, status_code=status.HTTP_201_CREATED)
async def scanner_create_scan(
    payload: ScannerCreateScanRequest, ctx: ApiKeyContext = Depends(get_api_key_context)
):
    if payload.project_id is not None and payload.project_id != ctx.project_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API key does not grant access to this project")
    project = await project_service.get_project_or_404(ctx.project_id)
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Project is archived")
    await _reject_foreign_repo(payload.repo_url, ctx, project.name)

    now = datetime.now(timezone.utc)
    scan = Scan(
        project_id=ctx.project_id,
        api_key_id=ctx.key_id,
        scan_type="cicd",
        triggered_by=payload.triggered_by or "cli",
        status="pending",
        scanner_version=payload.scanner_version,
        hostname=payload.hostname,
        git_commit=payload.git_commit,
        branch=payload.branch,
        repo_url=payload.repo_url,
        scan_label=payload.scan_label,
        ci_provider=payload.ci_provider,
        ci_build_id=payload.ci_build_id,
        ci_build_number=payload.ci_build_number,
        ci_build_url=payload.ci_build_url,
        created_at=now,
        updated_at=now,
    )
    await scan.insert()
    await scan_service.increment_scan_counter(project)
    await audit_service.record(
        "Scan Created",
        actor_type="api_key",
        project_id=ctx.project_id,
        target_type="scan",
        target_id=str(scan.id),
        metadata={
            "scanner_version": payload.scanner_version or "",
            "scan_label": payload.scan_label or "",
            "triggered_by": scan.triggered_by,
            "ci_provider": payload.ci_provider or "",
        },
    )
    # Same repo-scope resolution report ingestion uses, so the CI gate and the portal's counts are
    # computed from the identical exemption list.
    resolve = stats_svc.repo_key_resolver(await project_repo_service.list_repos(ctx.project_id))
    exemptions = await finding_review_service.accepted_exemptions(ctx.project_id, resolve(scan))
    return ScannerCreateScanResponse(
        scan_id=str(scan.id),
        status="pending",
        project_id=ctx.project_id,
        project_name=project.name,
        accepted_exemptions=exemptions,
    )


@router.post("/scans/{scan_id}/upload/json")
async def upload_json(scan_id: str, request: Request, ctx: ApiKeyContext = Depends(get_api_key_context)):
    scan = await _owned_scan(scan_id, ctx)
    raw = await request.body()
    try:
        report = GoReportIn.model_validate_json(raw)
    except ValidationError:
        raise HTTPException(422, "Invalid scanner report JSON")

    count = await report_ingestion_service.ingest(scan, report, raw.decode("utf-8", errors="replace"))
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
    await _owned_scan(scan_id, ctx)  # ownership check (404 if the key's project doesn't own it)
    data = await file.read()
    report = await Report.find_one(Report.scan_id == scan_id)
    if report:
        report.raw_html = data.decode("utf-8", errors="replace")
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

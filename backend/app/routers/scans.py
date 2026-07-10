from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.core.deps import get_current_user
from app.models.finding import Finding
from app.models.report import Report
from app.models.scan import Scan
from app.models.user import User
from app.schemas.common import Page
from app.schemas.report import FindingResponse, ReportResponse
from app.schemas.scan import ScanCreateRequest, ScanResponse
from app.services import audit_service, cloud_scan_service, project_service, scan_service

router = APIRouter(tags=["scans"])


def _to_finding_response(f: Finding) -> FindingResponse:
    return FindingResponse(
        id=str(f.id),
        scan_id=f.scan_id,
        project_id=f.project_id,
        finding_id=f.finding_id,
        fingerprint=f.fingerprint,
        rule_id=f.rule_id,
        rule_name=f.rule_name,
        category=f.category,
        severity=f.severity,
        confidence=f.confidence,
        message=f.message,
        location=f.location,
        language=f.language,
        evidence=f.evidence,
        cwe=f.cwe,
        owasp=f.owasp,
        references=f.references,
        metadata=f.metadata,
        kind=f.kind,
        secret=f.secret,
        dependency=f.dependency,
        config=f.config,
        rationale=f.rationale,
        remediation=f.remediation,
        taint_context=f.taint_context,
        created_at=f.created_at,
    )


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
async def create_scan(
    project_id: str,
    payload: ScanCreateRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    # Local and CI/CD scans are created by the scanner itself via API key (POST /api/v1/scans);
    # the UI shows setup instructions for those. Only cloud scans are created + executed here.
    if payload.scan_type != "cloud":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Local and CI/CD scans are created by the scanner via API key; use the setup instructions.",
        )
    project = await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Project is archived")

    now = datetime.now(timezone.utc)
    scan = Scan(
        project_id=project_id,
        scan_type="cloud",
        triggered_by="cloud",
        scan_label=payload.scan_label,
        repo_url=payload.repo_url,
        branch=payload.branch,
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
    background.add_task(cloud_scan_service.run_cloud_scan, str(scan.id), payload.repo_token)
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


@router.get("/scans/{scan_id}/report", response_model=ReportResponse)
async def get_scan_report(scan_id: str, user: User = Depends(get_current_user)):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    report = await Report.find_one(Report.scan_id == scan_id)
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No report for this scan yet")
    return ReportResponse(
        scan_id=report.scan_id,
        project_id=report.project_id,
        scanner_scan_id=report.scanner_scan_id,
        scanner_version=report.scanner_version,
        started_at=report.started_at,
        duration_ms=report.duration_ms,
        root_path=report.root_path,
        git_commit=report.git_commit,
        branch=report.branch,
        hostname=report.hostname,
        stats=report.stats,
        diagnostics=report.diagnostics,
        html_available=report.raw_html is not None,
        generated_at=report.generated_at,
    )


@router.get("/scans/{scan_id}/findings", response_model=Page)
async def list_scan_findings(
    scan_id: str,
    severity: str | None = Query(None),
    kind: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)

    criteria = [Finding.scan_id == scan_id]
    if severity:
        criteria.append(Finding.severity == severity)
    if kind:
        criteria.append(Finding.kind == kind)

    query = Finding.find(*criteria)
    total = await query.count()
    findings = await query.skip((page - 1) * page_size).limit(page_size).to_list()
    return Page(
        items=[_to_finding_response(f) for f in findings], total=total, page=page, page_size=page_size
    )

from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status

from app.core.deps import get_current_user
from app.models.finding import Finding
from app.models.report import Report
from app.models.scan import Scan
from app.models.user import User
from app.schemas.common import Page
from app.schemas.report import FindingResponse, ReportResponse
from app.schemas.scan import ScanCreateRequest, ScanResponse
from app.services import (
    audit_service,
    connection_service,
    pdf_report_service,
    project_repo_service,
    project_service,
    report_template_service,
    scan_queue_service,
    scan_service,
)

router = APIRouter(tags=["scans"])


def _to_finding_response(f: Finding) -> FindingResponse:
    return FindingResponse(
        id=str(f.id),
        scan_id=f.scan_id,
        project_id=f.project_id,
        project_repo_id=f.project_repo_id,
        finding_id=f.finding_id,
        fingerprint=f.fingerprint,
        rule_id=f.rule_id,
        rule_name=f.rule_name,
        category=f.category,
        severity=f.severity,
        confidence=f.confidence,
        priority_score=f.priority_score,
        priority_tier=f.priority_tier,
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
        project_repo_id=scan.project_repo_id,
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

    repo_url = payload.repo_url
    branch = payload.branch
    repo_token = payload.repo_token
    repo_token_auth_scheme = "bearer"

    if payload.project_repo_id:
        project_repo = await project_repo_service.get_project_repo_or_404(project_id, payload.project_repo_id)
        repo_url = project_repo.clone_url
        branch = project_repo.selected_branch
        repo_token = project_repo_service.decrypt_pat(project_repo)
        repo_token_auth_scheme = "basic" if project_repo.provider == "azure_devops" else "bearer"
    elif payload.connection_id:
        repo_token = await connection_service.get_decrypted_token(payload.connection_id, user)

    if not repo_url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "repo_url or project_repo_id is required")

    now = datetime.now(timezone.utc)
    scan = Scan(
        project_id=project_id,
        scan_type="cloud",
        triggered_by="cloud",
        status="queued",
        repo_token=repo_token,
        repo_token_auth_scheme=repo_token_auth_scheme,
        scan_label=payload.scan_label,
        repo_url=repo_url,
        project_repo_id=payload.project_repo_id,
        branch=branch,
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
    # Attempt to start immediately if capacity is free; the poll loop is the backstop otherwise.
    background.add_task(scan_queue_service.drain_queue)
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


@router.get("/scans/{scan_id}/report/pdf")
async def get_scan_report_pdf(scan_id: str, user: User = Depends(get_current_user)):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    report = await Report.find_one(Report.scan_id == scan_id)
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No report for this scan yet")

    project = await project_service.get_project_or_404(scan.project_id)
    template = await report_template_service.get_effective_template(project)
    findings = await Finding.find(Finding.scan_id == scan_id).to_list()
    pdf_bytes = await pdf_report_service.render_scan_report_pdf(scan, report, findings, template, project.name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="scan-{scan_id}-report.pdf"'},
    )


@router.get("/scans/{scan_id}/findings", response_model=Page)
async def list_scan_findings(
    scan_id: str,
    severity: str | None = Query(None),
    kind: str | None = Query(None),
    owasp: str | None = Query(None),
    priority: str | None = Query(None),
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
    if owasp:
        criteria.append(Finding.owasp == owasp)
    if priority:
        criteria.append(Finding.priority_tier == priority)

    query = Finding.find(*criteria)
    total = await query.count()
    findings = await query.skip((page - 1) * page_size).limit(page_size).to_list()
    return Page(
        items=[_to_finding_response(f) for f in findings], total=total, page=page, page_size=page_size
    )

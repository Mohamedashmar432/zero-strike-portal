from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models.project import Project
from app.models.scan import Scan
from app.models.user import User
from app.services import audit_service


async def get_scan_or_404(scan_id: str) -> Scan:
    scan = await Scan.get(scan_id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan


async def enqueue_repo_scan(
    project: Project,
    user: User,
    *,
    repo_url: str,
    branch: str | None,
    repo_token: str | None,
    repo_token_auth_scheme: str,
    project_repo_id: str | None,
    scan_label: str | None = None,
    triggered_by: str = "cloud",
) -> Scan:
    """Insert a `queued` cloud scan, bump the project's counter and audit it. The caller nudges
    scan_queue_service.drain_queue (the poll loop is the backstop) -- shared by the manual
    create-scan route and Repo Sync so both enqueue identically."""
    now = datetime.now(timezone.utc)
    scan = Scan(
        project_id=str(project.id),
        scan_type="cloud",
        triggered_by=triggered_by,
        status="queued",
        repo_token=repo_token,
        repo_token_auth_scheme=repo_token_auth_scheme,
        scan_label=scan_label,
        repo_url=repo_url,
        project_repo_id=project_repo_id,
        branch=branch,
        created_by=str(user.id),
        created_at=now,
        updated_at=now,
    )
    await scan.insert()
    await increment_scan_counter(project)
    await audit_service.record(
        "Scan Created",
        actor_user_id=str(user.id),
        project_id=str(project.id),
        target_type="scan",
        target_id=str(scan.id),
        metadata={"scan_type": scan.scan_type, "scan_label": scan.scan_label},
    )
    return scan


async def increment_scan_counter(project: Project) -> None:
    project.scan_count += 1
    project.last_scan_at = datetime.now(timezone.utc)
    await project.save()

from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models.project import Project
from app.models.scan import Scan


async def get_scan_or_404(scan_id: str) -> Scan:
    scan = await Scan.get(scan_id)
    if not scan:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scan not found")
    return scan


async def increment_scan_counter(project: Project) -> None:
    project.scan_count += 1
    project.last_scan_at = datetime.now(timezone.utc)
    await project.save()

"""Aggregates scanner health for the admin-only Scanner Status page: which binaries are
published for external CI/local download, the live cloud-scan queue, and recent failures —
the kind of thing that would have surfaced the CI/CD-binary-404 incident proactively instead
of via a support ticket.
"""

from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.scan import Scan
from app.models.scanner_binary import ScannerBinary
from app.schemas.scanner_status import (
    BinaryChecklistItem,
    FailureItem,
    QueueStatus,
    RunningScanItem,
    ScannerStatusResponse,
)
from app.services import cloud_scan_service

# The 5 combos zero-strike-code-scanner's release.yml actually builds and publishes — not all 6
# download_service._VALID_OS x _VALID_ARCH combos (windows/arm64 isn't a real release target).
EXPECTED_BINARIES = [
    ("linux", "amd64"),
    ("linux", "arm64"),
    ("windows", "amd64"),
    ("darwin", "amd64"),
    ("darwin", "arm64"),
]


async def binary_checklist() -> list[BinaryChecklistItem]:
    items = []
    for os_, arch in EXPECTED_BINARIES:
        doc = (
            await ScannerBinary.find(ScannerBinary.os == os_, ScannerBinary.arch == arch)
            .sort("-uploaded_at")
            .first_or_none()
        )
        if doc:
            items.append(
                BinaryChecklistItem(
                    os=os_,
                    arch=arch,
                    published=True,
                    version=doc.version,
                    uploaded_at=doc.uploaded_at,
                    uploaded_by=doc.uploaded_by,
                )
            )
        else:
            items.append(BinaryChecklistItem(os=os_, arch=arch, published=False))
    return items


async def queue_status() -> QueueStatus:
    running_docs = await Scan.find(Scan.status == "running", Scan.scan_type == "cloud").to_list()
    queued = await Scan.find(Scan.status == "queued", Scan.scan_type == "cloud").count()

    # Same threshold as scan_queue_service.reap_stuck_scans(). The stuck/not-stuck split is
    # computed via a Mongo-side comparison (not Python datetime arithmetic on the fetched docs)
    # because Motor returns naive UTC datetimes by default — comparing those with `.timestamp()`
    # would silently misinterpret them as local time.
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.scan_timeout_seconds * settings.queue_stuck_multiplier
    )
    stuck_ids = {
        str(s.id)
        for s in await Scan.find(
            Scan.status == "running", Scan.scan_type == "cloud", Scan.updated_at < cutoff
        ).to_list()
    }
    running_scans = [
        RunningScanItem(
            scan_id=str(scan.id),
            project_id=scan.project_id,
            started_at=scan.started_at,
            stuck=str(scan.id) in stuck_ids,
        )
        for scan in running_docs
    ]
    return QueueStatus(
        running=len(running_docs),
        queued=queued,
        max_concurrent=settings.max_concurrent_cloud_scans,
        running_scans=running_scans,
    )


async def recent_failures(limit: int = 10) -> list[FailureItem]:
    docs = await Scan.find(Scan.status == "failed").sort("-updated_at").limit(limit).to_list()
    return [
        FailureItem(
            scan_id=str(scan.id),
            project_id=scan.project_id,
            scan_type=scan.scan_type,
            error_message=scan.error_message,
            completed_at=scan.completed_at,
        )
        for scan in docs
    ]


async def get_status() -> ScannerStatusResponse:
    return ScannerStatusResponse(
        engine_available=cloud_scan_service.scanner_available(),
        binaries=await binary_checklist(),
        queue=await queue_status(),
        recent_failures=await recent_failures(),
    )

"""Self-hosted zerostrike binary storage & retrieval (MongoDB GridFS).

No new infra: Motor already ships GridFS support, and the team already prefers
Mongo-only storage over filesystem volumes (see Report.raw_json/raw_html). Binaries
are uploaded once per (version, os, arch) via the admin-only publish endpoint, then
served publicly — bootstrapping a CI runner shouldn't require portal credentials.
"""

import contextlib
import hashlib
import re
from datetime import datetime, timezone
from typing import Protocol

import structlog
from fastapi import HTTPException, status
from gridfs.errors import NoFile
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from app.core import dedupe
from app.core.config import settings
from app.db.mongo import get_database
from app.models.scanner_binary import ScannerBinary
from app.services import notification_service

logger = structlog.get_logger(__name__)

_BUCKET_NAME = "scanner_binaries"
_VALID_OS = {"linux", "windows", "darwin"}
_VALID_ARCH = {"amd64", "arm64"}
# Every publish() permanently adds ~20MB to GridFS; nothing pruned old versions before,
# and on an Atlas M0 cluster (512MB hard cap) that silently ran the whole app's writes
# into a wall. The GitHub Release stays the permanent source of truth, so pruning the
# portal's downloadable mirror down to the most recent releases is safe. How many to keep
# is settings.scanner_binary_retention_count.
#
# GridFS ids already alerted on. A CI runner retries a dead download every few minutes, and
# one alert per request would bury the admin's inbox; once per process per file is enough.
_alerted_missing: set[str] = set()
# publish() streams in 1MB slices instead of holding the whole ~20MB binary as one bytes
# object. Buffering it grew the container's RSS across a release run (5 uploads back to
# back, ~100MB) until the platform killed the process mid-release — v0.32.0 published
# 2/5 binaries and the other three got the edge proxy's "Application failed to respond"
# 502 while the app restarted. Starlette already spools the request body to a temp file
# past 1MB, so reading it back in slices keeps peak memory flat regardless of binary size.
_UPLOAD_CHUNK_BYTES = 1 << 20


class SupportsAsyncRead(Protocol):
    async def read(self, size: int) -> bytes: ...


def _bucket() -> AsyncIOMotorGridFSBucket:
    return AsyncIOMotorGridFSBucket(get_database(), bucket_name=_BUCKET_NAME)


def parse_os_arch(os_arch: str) -> tuple[str, str]:
    """Split a `{os}-{arch}` path segment, e.g. "linux-amd64" -> ("linux", "amd64")."""
    parts = os_arch.split("-")
    if len(parts) != 2 or parts[0] not in _VALID_OS or parts[1] not in _VALID_ARCH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid os-arch '{os_arch}'")
    return parts[0], parts[1]


def validate_os_arch(os_: str, arch: str) -> None:
    if os_ not in _VALID_OS or arch not in _VALID_ARCH:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid os '{os_}' or arch '{arch}'")


def build_filename(os_: str, arch: str) -> str:
    ext = ".exe" if os_ == "windows" else ""
    return f"zerostrike_{os_}_{arch}{ext}"


async def resolve_binary(version: str, os_: str, arch: str) -> ScannerBinary:
    """`version="latest"` resolves to the most recently uploaded binary for this (os, arch)."""
    query = [ScannerBinary.os == os_, ScannerBinary.arch == arch]
    if version != "latest":
        query.append(ScannerBinary.version == version)
    doc = await ScannerBinary.find(*query).sort("-uploaded_at").first_or_none()
    if not doc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"no zerostrike binary for {os_}-{arch} at version '{version}' — a portal admin must "
            "publish it (POST /api/v1/admin/downloads/zerostrike; see docs/AZURE_DEVOPS_CLASSIC_PIPELINE.md)",
        )
    return doc


async def resolve_version_binaries(version: str) -> list[ScannerBinary]:
    """All (os, arch) binaries sharing one version — used for the checksums.txt listing."""
    if version == "latest":
        newest = await ScannerBinary.find_all().sort("-uploaded_at").first_or_none()
        if not newest:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "no zerostrike binaries uploaded yet")
        version = newest.version
    docs = await ScannerBinary.find(ScannerBinary.version == version).to_list()
    if not docs:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"no zerostrike binaries for version '{version}'")
    return docs


async def _blob_exists(file_id) -> bool:
    return await get_database()[f"{_BUCKET_NAME}.files"].find_one({"_id": file_id}, {"_id": 1}) is not None


async def open_download_stream(doc: ScannerBinary):
    """Open the stored file, turning a row whose GridFS file is gone into a 404 plus an admin alert.

    The metadata row and the blob are two writes that nothing keeps in step, so a row can outlive
    its file (a failed publish, a half-finished prune, a restored database). That used to escape as
    an unhandled 500 on every CI download.
    """
    try:
        return await _bucket().open_download_stream(doc.gridfs_file_id)
    except NoFile:
        await _report_missing_blob(doc)
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"zerostrike {doc.os}-{doc.arch}@{doc.version} is listed but its file is missing from "
            "storage — a portal admin must re-run the scanner release pipeline to republish it",
        ) from None


def _failure_reason(exc: HTTPException, checksums: bool) -> str:
    detail = str(exc.detail)
    if "missing from storage" in detail:
        return "file_missing"
    if checksums:
        return "checksum_missing"
    if "uploaded yet" in detail:
        return "none_published"
    if "binaries for version" in detail:
        return "unknown_version"
    return "no_binary"


@contextlib.asynccontextmanager
async def report_failures(version: str, os_arch: str | None = None):
    """Alert admins when a public download endpoint turns a CI pipeline away: unknown version, no build
    for that OS/arch, a listed-but-missing file, or no checksum file. Re-raises the original error.

    Once per (version, os-arch, reason) per hour, and at most 10 alerts an hour overall: this endpoint
    is unauthenticated, so anyone can invent versions -- the cap keeps that from becoming a spam
    cannon. A 400 (malformed os-arch) is scanner noise, not an outage, and is never alerted."""
    try:
        yield
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            reason = _failure_reason(exc, checksums=os_arch is None)
            safe_version = re.sub(r"[^A-Za-z0-9._+-]", "?", version)[:64]
            target = os_arch or "checksums.txt"
            if dedupe.alerts.first(
                f"scanner.download_failed:{safe_version}:{target}:{reason}",
                3600,
                group="scanner.download_failed",
                group_cap=10,
            ):
                await notification_service.notify(
                    "scanner.download_failed",
                    title=f"Scanner download failed: {target} {safe_version}",
                    body=f"A CI download of zerostrike {safe_version} ({target}) was refused: {exc.detail}",
                    link="/admin/scanner-status",
                    severity="error",
                    facts=[("Version", safe_version), ("Target", target), ("Reason", reason)],
                )
        raise


async def _report_missing_blob(doc: ScannerBinary) -> None:
    file_id = str(doc.gridfs_file_id)
    if file_id in _alerted_missing:
        return
    _alerted_missing.add(file_id)
    logger.error(
        "scanner_binary_blob_missing", version=doc.version, os=doc.os, arch=doc.arch, gridfs_file_id=file_id
    )
    await notification_service.notify(
        "scanner.binary_missing",
        title=f"Scanner download missing: {doc.os}-{doc.arch} {doc.version}",
        body=(
            f"The portal lists zerostrike {doc.version} for {doc.os}-{doc.arch}, but its file is gone "
            "from storage, so CI pipelines that download it get a 404. Re-run the scanner release "
            "pipeline to republish it; publishing replaces the dead record."
        ),
        link="/admin/scanner-status",
        severity="error",
    )


async def _prune_old_versions(os_: str, arch: str) -> None:
    """Delete all but the newest `scanner_binary_retention_count` binaries for this (os, arch)."""
    stale = (
        await ScannerBinary.find(ScannerBinary.os == os_, ScannerBinary.arch == arch)
        .sort("-uploaded_at")
        .skip(max(1, settings.scanner_binary_retention_count))
        .to_list()
    )
    for doc in stale:
        try:
            await _bucket().delete(doc.gridfs_file_id)
        except NoFile:
            pass  # already gone; still drop the row, or it would dangle and block every later prune
        await doc.delete()
        logger.info("scanner_binary_pruned", version=doc.version, os=os_, arch=arch)


async def publish(
    *, version: str, os_: str, arch: str, source: SupportsAsyncRead, uploaded_by: str
) -> ScannerBinary:
    """Stream `source` into GridFS and insert its ScannerBinary metadata (identical re-upload is a no-op; different bytes -> 409).

    `source` is anything with an async `read(size)` — in practice Starlette's `UploadFile`.
    """
    validate_os_arch(os_, arch)
    filename = build_filename(os_, arch)

    digest = hashlib.sha256()
    size_bytes = 0
    grid_in = _bucket().open_upload_stream(filename)
    stored = False

    try:
        while chunk := await source.read(_UPLOAD_CHUNK_BYTES):
            digest.update(chunk)
            size_bytes += len(chunk)
            await grid_in.write(chunk)
        await grid_in.close()
        stored = True

        # A published (version, os, arch) is immutable: the same bytes again is a pipeline
        # retry (idempotent success), different bytes is refused so a leaked or compromised
        # admin credential can't silently swap a binary CI runners already trust by version.
        # The hash is only known after streaming, so the new GridFS file is dropped either way.
        existing = await ScannerBinary.find_one(
            ScannerBinary.version == version, ScannerBinary.os == os_, ScannerBinary.arch == arch
        )
        if existing and await _blob_exists(existing.gridfs_file_id):
            await _bucket().delete(grid_in._id)
            stored = False
            if existing.sha256 == digest.hexdigest():
                return existing
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{os_}-{arch}@{version} is already published with different content; "
                "publish a new version",
            )

        if existing:
            # The row survived but its file did not, so nothing can be downloaded and the
            # "same bytes is a no-op" shortcut above would leave it broken forever. Nothing
            # trusted is being swapped (there is no stored binary), so repoint the row at the
            # fresh upload instead of refusing.
            logger.warning("scanner_binary_blob_repaired", version=version, os=os_, arch=arch)
            existing.gridfs_file_id = grid_in._id
            existing.sha256 = digest.hexdigest()
            existing.size_bytes = size_bytes
            existing.uploaded_at = datetime.now(timezone.utc)
            existing.uploaded_by = uploaded_by
            await existing.save()
            doc = existing
        else:
            doc = ScannerBinary(
                version=version,
                os=os_,
                arch=arch,
                filename=filename,
                gridfs_file_id=grid_in._id,
                sha256=digest.hexdigest(),
                size_bytes=size_bytes,
                uploaded_at=datetime.now(timezone.utc),
                uploaded_by=uploaded_by,
            )
            await doc.insert()
    except HTTPException:
        raise
    except Exception as exc:
        # Don't leave half-written chunks behind: on an M0 cluster orphaned GridFS files
        # are indistinguishable from real ones and eat the 512MB cap silently.
        try:
            if stored:
                await _bucket().delete(grid_in._id)
            else:
                await grid_in.abort()
        except Exception:
            logger.warning("scanner_binary_upload_cleanup_failed", os=os_, arch=arch, exc_info=True)
        # Bare 500s from this endpoint are undebuggable from the CI side (the release
        # pipeline's curl -f swallows the response body) — log full context server-side
        # and surface a real reason to the caller instead of Starlette's generic 500.
        logger.exception(
            "scanner_binary_publish_failed",
            version=version,
            os=os_,
            arch=arch,
            size_bytes=size_bytes,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"failed to publish {os_}-{arch}@{version}: {exc.__class__.__name__}: {exc}",
        ) from exc

    try:
        await _prune_old_versions(os_, arch)
    except Exception:
        # Best-effort: the upload itself already succeeded, don't fail the request over cleanup.
        logger.warning("scanner_binary_prune_failed", os=os_, arch=arch, exc_info=True)

    return doc

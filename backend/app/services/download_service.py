"""Self-hosted zerostrike binary storage & retrieval (MongoDB GridFS).

No new infra: Motor already ships GridFS support, and the team already prefers
Mongo-only storage over filesystem volumes (see Report.raw_json/raw_html). Binaries
are uploaded once per (version, os, arch) via the admin-only publish endpoint, then
served publicly — bootstrapping a CI runner shouldn't require portal credentials.
"""

import hashlib
from datetime import datetime, timezone
from typing import Protocol

import structlog
from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from app.db.mongo import get_database
from app.models.scanner_binary import ScannerBinary

logger = structlog.get_logger(__name__)

_BUCKET_NAME = "scanner_binaries"
_VALID_OS = {"linux", "windows", "darwin"}
_VALID_ARCH = {"amd64", "arm64"}
# Every publish() permanently adds ~20MB to GridFS; nothing pruned old versions before,
# and on an Atlas M0 cluster (512MB hard cap) that silently ran the whole app's writes
# into a wall. The GitHub Release stays the permanent source of truth, so pruning the
# portal's downloadable mirror down to the most recent releases is safe.
_RETENTION_COUNT = 2
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
            status.HTTP_404_NOT_FOUND, f"no zerostrike binary for {os_}-{arch} at version '{version}'"
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


async def open_download_stream(doc: ScannerBinary):
    return await _bucket().open_download_stream(doc.gridfs_file_id)


async def _prune_old_versions(os_: str, arch: str) -> None:
    """Delete all but the `_RETENTION_COUNT` most-recently-uploaded binaries for this (os, arch)."""
    stale = (
        await ScannerBinary.find(ScannerBinary.os == os_, ScannerBinary.arch == arch)
        .sort("-uploaded_at")
        .skip(_RETENTION_COUNT)
        .to_list()
    )
    for doc in stale:
        await _bucket().delete(doc.gridfs_file_id)
        await doc.delete()
        logger.info("scanner_binary_pruned", version=doc.version, os=os_, arch=arch)


async def publish(
    *, version: str, os_: str, arch: str, source: SupportsAsyncRead, uploaded_by: str
) -> ScannerBinary:
    """Stream `source` into GridFS and upsert its ScannerBinary metadata (re-uploads replace).

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

        # Replace the old version only once the new bytes are safely in GridFS. The release
        # pipeline now retries 5xx, and a retry that deleted first would leave the version
        # with no binary at all if the second attempt also died mid-upload.
        existing = await ScannerBinary.find_one(
            ScannerBinary.version == version, ScannerBinary.os == os_, ScannerBinary.arch == arch
        )
        if existing:
            await _bucket().delete(existing.gridfs_file_id)
            await existing.delete()

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

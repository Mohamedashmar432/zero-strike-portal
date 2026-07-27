"""Self-hosted zerostrike binary storage & retrieval (MongoDB GridFS).

No new infra: Motor already ships GridFS support, and the team already prefers
Mongo-only storage over filesystem volumes (see Report.raw_json/raw_html). Binaries
are uploaded once per (version, os, arch) via the admin-only publish endpoint, then
served publicly — bootstrapping a CI runner shouldn't require portal credentials.
"""

import hashlib
from datetime import datetime, timezone

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
    *, version: str, os_: str, arch: str, data: bytes, uploaded_by: str
) -> ScannerBinary:
    """Store `data` in GridFS and upsert its ScannerBinary metadata doc (re-uploads replace)."""
    validate_os_arch(os_, arch)
    filename = build_filename(os_, arch)
    sha256 = hashlib.sha256(data).hexdigest()

    try:
        existing = await ScannerBinary.find_one(
            ScannerBinary.version == version, ScannerBinary.os == os_, ScannerBinary.arch == arch
        )
        if existing:
            await _bucket().delete(existing.gridfs_file_id)
            await existing.delete()

        file_id = await _bucket().upload_from_stream(filename, data)
        doc = ScannerBinary(
            version=version,
            os=os_,
            arch=arch,
            filename=filename,
            gridfs_file_id=file_id,
            sha256=sha256,
            size_bytes=len(data),
            uploaded_at=datetime.now(timezone.utc),
            uploaded_by=uploaded_by,
        )
        await doc.insert()
    except Exception as exc:
        # Bare 500s from this endpoint are undebuggable from the CI side (the release
        # pipeline's curl -f swallows the response body) — log full context server-side
        # and surface a real reason to the caller instead of Starlette's generic 500.
        logger.exception(
            "scanner_binary_publish_failed",
            version=version,
            os=os_,
            arch=arch,
            size_bytes=len(data),
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

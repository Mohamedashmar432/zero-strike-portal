"""Self-hosted zerostrike binary storage & retrieval (MongoDB GridFS).

No new infra: Motor already ships GridFS support, and the team already prefers
Mongo-only storage over filesystem volumes (see Report.raw_json/raw_html). Binaries
are uploaded once per (version, os, arch) via the admin-only publish endpoint, then
served publicly — bootstrapping a CI runner shouldn't require portal credentials.
"""

import hashlib
from datetime import datetime, timezone

from fastapi import HTTPException, status
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from app.db.mongo import get_database
from app.models.scanner_binary import ScannerBinary

_BUCKET_NAME = "scanner_binaries"
_VALID_OS = {"linux", "windows", "darwin"}
_VALID_ARCH = {"amd64", "arm64"}


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


async def publish(
    *, version: str, os_: str, arch: str, data: bytes, uploaded_by: str
) -> ScannerBinary:
    """Store `data` in GridFS and upsert its ScannerBinary metadata doc (re-uploads replace)."""
    validate_os_arch(os_, arch)
    filename = build_filename(os_, arch)
    sha256 = hashlib.sha256(data).hexdigest()

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
    return doc

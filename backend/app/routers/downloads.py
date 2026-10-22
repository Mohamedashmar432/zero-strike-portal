from fastapi import APIRouter, Response

from app.schemas.download import ScannerBinaryInfo
from app.services import download_service

router = APIRouter(prefix="/downloads/zerostrike", tags=["downloads"])


@router.get("/{version}/checksums.txt")
async def download_checksums(version: str) -> Response:
    docs = await download_service.resolve_version_binaries(version)
    lines = [f"{doc.sha256}  {doc.filename}" for doc in docs]
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


@router.get("/{version}/{os_arch}/info", response_model=ScannerBinaryInfo)
async def binary_info(version: str, os_arch: str) -> ScannerBinaryInfo:
    """Metadata only (no bytes): lets a pipeline confirm a binary is published and read its sha256."""
    os_, arch = download_service.parse_os_arch(os_arch)
    doc = await download_service.resolve_binary(version, os_, arch)
    return ScannerBinaryInfo(
        version=doc.version,
        os=doc.os,
        arch=doc.arch,
        filename=doc.filename,
        sha256=doc.sha256,
        size_bytes=doc.size_bytes,
        uploaded_at=doc.uploaded_at,
    )


@router.get("/{version}/{os_arch}")
async def download_binary(version: str, os_arch: str) -> Response:
    os_, arch = download_service.parse_os_arch(os_arch)
    doc = await download_service.resolve_binary(version, os_, arch)
    # Binaries are small enough (a Go CLI, tens of MB) to buffer whole — simpler than a
    # chunked streaming response; revisit if that assumption ever stops holding.
    stream = await download_service.open_download_stream(doc)
    data = await stream.read()
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{doc.filename}"',
            "X-Checksum-Sha256": doc.sha256,
        },
    )

from fastapi import APIRouter, Response

from app.services import download_service

router = APIRouter(prefix="/downloads/zerostrike", tags=["downloads"])


@router.get("/{version}/checksums.txt")
async def download_checksums(version: str) -> Response:
    docs = await download_service.resolve_version_binaries(version)
    lines = [f"{doc.sha256}  {doc.filename}" for doc in docs]
    return Response(content="\n".join(lines) + "\n", media_type="text/plain")


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

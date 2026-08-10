from fastapi import APIRouter, Depends, Form, UploadFile

from app.core.deps import require_admin
from app.models.scanner_binary import ScannerArch, ScannerOs
from app.models.user import User
from app.services import download_service

router = APIRouter(prefix="/admin/downloads/zerostrike", tags=["downloads"])


@router.post("")
async def publish_binary(
    file: UploadFile,
    version: str = Form(...),
    os: ScannerOs = Form(...),
    arch: ScannerArch = Form(...),
    user: User = Depends(require_admin),
):
    # Hand the UploadFile through unread — publish() streams it into GridFS. Reading it
    # whole here is what pushed the container over its memory limit during a release.
    doc = await download_service.publish(
        version=version, os_=os, arch=arch, source=file, uploaded_by=str(user.id)
    )
    return {
        "version": doc.version,
        "os": doc.os,
        "arch": doc.arch,
        "filename": doc.filename,
        "sha256": doc.sha256,
        "size_bytes": doc.size_bytes,
    }

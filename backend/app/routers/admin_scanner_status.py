from fastapi import APIRouter, Depends

from app.core.deps import require_admin
from app.schemas.scanner_status import ScannerStatusResponse
from app.services import scanner_status_service

router = APIRouter(prefix="/admin/scanner-status", tags=["scanner-status"], dependencies=[Depends(require_admin)])


@router.get("", response_model=ScannerStatusResponse)
async def get_scanner_status() -> ScannerStatusResponse:
    return await scanner_status_service.get_status()

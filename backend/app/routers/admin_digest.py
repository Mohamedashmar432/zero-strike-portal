"""Admin configuration, preview and test-send for the Teams digest."""

from fastapi import APIRouter, Depends

from app.core.deps import require_admin
from app.models.digest_settings import DigestSettings
from app.models.user import User
from app.schemas.digest import (
    DigestPreview,
    DigestSendResponse,
    DigestSettingsRequest,
    DigestSettingsResponse,
)
from app.services import audit_service, digest_service

router = APIRouter(prefix="/admin/digest-settings", tags=["admin"], dependencies=[Depends(require_admin)])

_FIELDS = tuple(DigestSettingsRequest.model_fields)


def _response(row: DigestSettings) -> DigestSettingsResponse:
    return DigestSettingsResponse(
        **{f: getattr(row, f) for f in _FIELDS},
        last_sent_at=row.last_sent_at,
        last_status=row.last_status,
        last_error=row.last_error,
    )


@router.get("", response_model=DigestSettingsResponse)
async def get_digest_settings():
    return _response(await digest_service.get_settings())


@router.put("", response_model=DigestSettingsResponse)
async def put_digest_settings(payload: DigestSettingsRequest, admin: User = Depends(require_admin)):
    row = await digest_service.get_settings()
    for field in _FIELDS:
        setattr(row, field, getattr(payload, field))
    await row.save()
    await audit_service.record(
        "Digest Settings Updated",
        actor_user_id=str(admin.id),
        target_type="digest",
        metadata={
            "enabled": row.enabled,
            "frequency": row.frequency,
            "time_utc": f"{row.hour_utc:02d}:{row.minute_utc:02d}",
            "projects": len(row.project_ids) or "all",
        },
    )
    return _response(row)


@router.get("/preview", response_model=DigestPreview)
async def preview_digest():
    return await digest_service.build_preview(await digest_service.get_settings())


@router.post("/send-test", response_model=DigestSendResponse)
async def send_test_digest(admin: User = Depends(require_admin)):
    result = await digest_service.send_digest(await digest_service.get_settings())
    await digest_service.record_outcome(result)
    await audit_service.record(
        "Digest Test Sent",
        actor_user_id=str(admin.id),
        target_type="digest",
        metadata={"channels": result.sent, "errors": len(result.errors)},
    )
    return result

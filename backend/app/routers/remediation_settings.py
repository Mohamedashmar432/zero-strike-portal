"""Admin-only policy for AI Auto-Fix. Both endpoints are admin-only (mirrors the AI Provider
config surface); the frontend only fetches inside a RequireRole('admin') gate. PUT is audited.
"""

from fastapi import APIRouter, Depends

from app.core.deps import require_admin
from app.models.remediation_settings import RemediationSettings
from app.models.user import User
from app.schemas.remediation_settings import (
    RemediationSettingsResponse,
    RemediationSettingsUpdateRequest,
)
from app.services import audit_service, remediation_settings_service

router = APIRouter(prefix="/remediation-settings", tags=["remediation-settings"])


def _to_response(cfg: RemediationSettings) -> RemediationSettingsResponse:
    return RemediationSettingsResponse(
        enabled=cfg.enabled,
        confidence_threshold=cfg.confidence_threshold,
        max_findings_per_job=cfg.max_findings_per_job,
        blocking_severities=cfg.blocking_severities,
    )


@router.get("/settings", response_model=RemediationSettingsResponse)
async def get_remediation_settings(user: User = Depends(require_admin)):
    return _to_response(await remediation_settings_service.get_settings())


@router.put("/settings", response_model=RemediationSettingsResponse)
async def update_remediation_settings(
    payload: RemediationSettingsUpdateRequest, user: User = Depends(require_admin)
):
    changed = payload.model_dump(exclude_unset=True)
    cfg = await remediation_settings_service.update_settings(updated_by=str(user.id), **changed)
    await audit_service.record(
        "Auto-Fix Settings Updated",
        actor_user_id=str(user.id),
        target_type="remediation_settings",
        metadata=changed,
    )
    return _to_response(cfg)

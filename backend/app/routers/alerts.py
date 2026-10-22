"""Alert channels. Project alerts: owner or portal admin only (the webhook is a secret and the
mailboxes are third-party addresses). Global webhook: portal admin only."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user, require_admin
from app.core.security import encrypt_secret
from app.models.project import Project
from app.models.user import User
from app.schemas.alerts import (
    GlobalAlertsResponse,
    GlobalAlertsUpdateRequest,
    ProjectAlertsResponse,
    ProjectAlertsUpdateRequest,
)
from app.schemas.common import MessageResponse
from app.services import alert_service, audit_service, project_service, workspace_settings_service

router = APIRouter(tags=["alerts"])


def _encrypt_vetted(url: str) -> str | None:
    """"" clears the stored webhook; anything else must pass the SSRF vet or is a 422."""
    if not url.strip():
        return None
    try:
        return encrypt_secret(alert_service.vet_webhook_url(url))
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def _project_response(p: Project) -> ProjectAlertsResponse:
    return ProjectAlertsResponse(
        webhook_enabled=p.alert_webhook_enabled,
        webhook_configured=bool(p.alert_webhook_enc),
        webhook_host=alert_service.host_of(p.alert_webhook_enc),
        email_enabled=p.alert_email_enabled,
        emails=p.alert_emails,
        triggers=p.alert_triggers,
    )


@router.get("/projects/{project_id}/alerts", response_model=ProjectAlertsResponse)
async def get_project_alerts(project_id: str, user: User = Depends(get_current_user)):
    project = await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)
    return _project_response(project)


@router.put("/projects/{project_id}/alerts", response_model=ProjectAlertsResponse)
async def update_project_alerts(
    project_id: str, payload: ProjectAlertsUpdateRequest, user: User = Depends(get_current_user)
):
    project = await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)
    if payload.webhook_url is not None:
        project.alert_webhook_enc = _encrypt_vetted(payload.webhook_url)
    if payload.webhook_enabled is not None:
        project.alert_webhook_enabled = payload.webhook_enabled
    if payload.email_enabled is not None:
        project.alert_email_enabled = payload.email_enabled
    if payload.emails is not None:
        # Case-insensitive de-dupe, order kept: the cap is three *distinct* mailboxes.
        seen: dict[str, str] = {}
        for e in payload.emails:
            seen.setdefault(str(e).lower(), str(e))
        project.alert_emails = list(seen.values())
    if payload.triggers is not None:
        project.alert_triggers = list(dict.fromkeys(payload.triggers))
    if project.alert_webhook_enabled and not project.alert_webhook_enc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add a webhook URL before enabling it")
    if project.alert_email_enabled and not project.alert_emails:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add at least one email before enabling it")
    project.updated_at = datetime.now(timezone.utc)
    await project.save()
    # Never the URL: only which channels are on and how many mailboxes.
    await audit_service.record(
        "Project Alerts Updated",
        actor_user_id=str(user.id),
        project_id=project_id,
        metadata={
            "webhook_enabled": project.alert_webhook_enabled,
            "email_enabled": project.alert_email_enabled,
            "email_count": len(project.alert_emails),
            "triggers": project.alert_triggers,
        },
    )
    return _project_response(project)


@router.post("/projects/{project_id}/alerts/test", response_model=MessageResponse)
async def test_project_alerts(project_id: str, user: User = Depends(get_current_user)):
    project = await project_service.get_project_or_404(project_id)
    await project_service.require_owner_or_admin(project_id, user)
    if not project.alert_webhook_enc:
        raise HTTPException(status.HTTP_409_CONFLICT, "No webhook URL is configured")
    from app.core.security import decrypt_secret

    try:
        await alert_service.post_webhook(
            decrypt_secret(project.alert_webhook_enc),
            f"{project.name}: test alert",
            "This is a test alert from thinkShield. Alerts for this project will arrive here.",
            f"/projects/{project_id}",
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Webhook delivery failed ({type(exc).__name__})")
    await audit_service.record(
        "Alert Test Sent",
        actor_user_id=str(user.id),
        project_id=project_id,
        target_type="alert",
        metadata={"channel": "webhook", "project": project.name},
    )
    return MessageResponse(message="Test alert sent")


# --- portal-wide webhook ---------------------------------------------------------------------


def _global_response(ws) -> GlobalAlertsResponse:
    return GlobalAlertsResponse(
        webhook_enabled=ws.alert_webhook_enabled,
        webhook_configured=bool(ws.alert_webhook_enc),
        webhook_host=alert_service.host_of(ws.alert_webhook_enc),
    )


@router.get("/workspace-settings/alerts", response_model=GlobalAlertsResponse)
async def get_global_alerts(_: User = Depends(require_admin)):
    return _global_response(await workspace_settings_service.get_workspace_settings())


@router.put("/workspace-settings/alerts", response_model=GlobalAlertsResponse)
async def update_global_alerts(payload: GlobalAlertsUpdateRequest, user: User = Depends(require_admin)):
    ws = await workspace_settings_service.get_workspace_settings()
    changed: dict = {}
    enc = ws.alert_webhook_enc
    if payload.webhook_url is not None:
        enc = _encrypt_vetted(payload.webhook_url)
        changed["alert_webhook_enc"] = enc
    if payload.webhook_enabled is not None:
        changed["alert_webhook_enabled"] = payload.webhook_enabled
    if changed.get("alert_webhook_enabled", ws.alert_webhook_enabled) and not enc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Add a webhook URL before enabling it")
    ws = await workspace_settings_service.update_workspace_settings(updated_by=str(user.id), **changed)
    await audit_service.record(
        "Global Alerts Updated",
        actor_user_id=str(user.id),
        target_type="workspace_settings",
        metadata={"webhook_enabled": ws.alert_webhook_enabled},
    )
    return _global_response(ws)


@router.post("/workspace-settings/alerts/test", response_model=MessageResponse)
async def test_global_alerts(user: User = Depends(require_admin)):
    from app.core.security import decrypt_secret

    ws = await workspace_settings_service.get_workspace_settings()
    if not ws.alert_webhook_enc:
        raise HTTPException(status.HTTP_409_CONFLICT, "No webhook URL is configured")
    try:
        await alert_service.post_webhook(
            decrypt_secret(ws.alert_webhook_enc),
            "thinkShield: test alert",
            "This is a test alert. Portal-wide admin events will arrive here.",
            "/settings/notifications",
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Webhook delivery failed ({type(exc).__name__})")
    await audit_service.record(
        "Alert Test Sent", actor_user_id=str(user.id), target_type="alert", metadata={"channel": "global webhook"}
    )
    return MessageResponse(message="Test alert sent")

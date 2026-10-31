"""Admin control of live dependency alerts (docs/LIVE_DEPENDENCY_ALERTS.md section 8): status, the
workspace policy, and a manual "check now" / dry-run preview. Portal admins only."""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import require_admin
from app.models.user import User
from app.schemas.live_alerts import LiveAlertRunResponse, LiveAlertSettingsUpdate, LiveAlertStatus
from app.services import audit_service, live_alert_service, workspace_settings_service

router = APIRouter(prefix="/admin/live-alerts", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("", response_model=LiveAlertStatus)
async def get_live_alerts_status():
    return await live_alert_service.status()


@router.put("", response_model=LiveAlertStatus)
async def update_live_alert_settings(payload: LiveAlertSettingsUpdate, admin: User = Depends(require_admin)):
    ws = await workspace_settings_service.get_workspace_settings()
    changed: dict = {}
    if payload.enabled is not None:
        changed["live_alerts_enabled"] = payload.enabled
    if payload.min_severity is not None:
        changed["live_alerts_min_severity"] = payload.min_severity
    if payload.include_malicious is not None:
        changed["live_alerts_include_malicious"] = payload.include_malicious
    turned_on = payload.enabled is True and not ws.live_alerts_enabled
    if changed:
        await workspace_settings_service.update_workspace_settings(updated_by=str(admin.id), **changed)
    if turned_on:
        # Whatever was published while alerts were off is not backfilled: the next run re-baselines.
        await live_alert_service.reset_cursors()
    await audit_service.record(
        "Live Alert Settings Changed",
        actor_user_id=str(admin.id),
        target_type="workspace_settings",
        metadata={**changed, "cursors_reset": turned_on},
    )
    return await live_alert_service.status()


@router.post("/run", response_model=LiveAlertRunResponse)
async def run_live_alert_check(dry_run: bool = Query(False), admin: User = Depends(require_admin)):
    """Check the feed now. A dry run reads and matches but claims nothing, moves no cursor and delivers
    nothing; it returns the cards that would be sent. 409 while another run holds the lease."""
    summary = await live_alert_service.run_once(force=True, dry_run=dry_run)
    await audit_service.record(
        "Live Alert Check Triggered",
        actor_user_id=str(admin.id),
        target_type="advisory_watch",
        metadata={"dry_run": dry_run, "status": summary.status, "alerts": summary.alerts},
    )
    if summary.status == "busy":
        raise HTTPException(status.HTTP_409_CONFLICT, summary.reason or "A check is already running")
    return LiveAlertRunResponse(
        status=summary.status, dry_run=dry_run, summary=summary.to_dict(), previews=summary.previews
    )

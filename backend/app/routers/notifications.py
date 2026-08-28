"""Per-user notification inbox and preferences.

Everything here is scoped to the calling user — there is no admin view of someone else's
inbox, and no endpoint takes a user_id. Who receives which event is decided by
notification_service from project membership and portal role, not by a request parameter.
"""

from fastapi import APIRouter, Depends, Query

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.notification_events import defaults_for, visible_events
from app.core.timeutils import as_utc
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import (
    MarkReadRequest,
    NotificationEventOut,
    NotificationListResponse,
    NotificationOut,
    NotificationPreferencesResponse,
    NotificationPreferencesUpdateRequest,
)
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=str(n.id),
        event=n.event,
        title=n.title,
        body=n.body,
        severity=n.severity,
        project_id=n.project_id,
        link=n.link,
        # Motor returns naive datetimes; without as_utc the JSON has no offset and the
        # browser's `new Date(...)` reads it as local time -- a notification from a minute
        # ago renders as hours old (see core.timeutils).
        read_at=as_utc(n.read_at),
        created_at=as_utc(n.created_at),
    )


async def _inbox(user_id: str, limit: int) -> NotificationListResponse:
    """Shared by both endpoints. Never call a route handler directly to reuse it — FastAPI
    parameter defaults are `Query(...)`/`Depends(...)` marker objects, so a direct call
    passes the marker itself rather than the value FastAPI would have resolved.
    """
    rows = await notification_service.list_for_user(user_id, limit=limit)
    return NotificationListResponse(
        items=[_to_out(n) for n in rows],
        unread_count=await notification_service.unread_count(user_id),
    )


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    limit: int = Query(50, ge=1, le=200), user: User = Depends(get_current_user)
):
    return await _inbox(str(user.id), limit)


@router.post("/read", response_model=NotificationListResponse)
async def mark_notifications_read(
    payload: MarkReadRequest, user: User = Depends(get_current_user)
):
    await notification_service.mark_read(str(user.id), payload.notification_id)
    return await _inbox(str(user.id), 50)


def _preferences(user: User) -> NotificationPreferencesResponse:
    """Scoped to what this user can actually receive — see notification_events.visible_events.

    Stored subscriptions are filtered the same way, so an admin who is later demoted stops
    being shown switches for events that no longer reach them, without their stored
    preference being rewritten behind their back.
    """
    is_admin = user.role == "admin"
    allowed = {e.key for e in visible_events(is_admin=is_admin)}
    stored_in_app = user.notify_in_app
    stored_email = user.notify_email
    return NotificationPreferencesResponse(
        events=[
            NotificationEventOut(
                key=e.key, label=e.label, description=e.description, audience=e.audience
            )
            for e in visible_events(is_admin=is_admin)
        ],
        in_app=(
            [k for k in stored_in_app if k in allowed]
            if stored_in_app is not None
            else defaults_for(is_admin=is_admin, channel="in_app")
        ),
        email=(
            [k for k in stored_email if k in allowed]
            if stored_email is not None
            else defaults_for(is_admin=is_admin, channel="email")
        ),
        email_delivery_configured=bool(settings.smtp_host),
    )


@router.get("/preferences", response_model=NotificationPreferencesResponse)
async def get_notification_preferences(user: User = Depends(get_current_user)):
    return _preferences(user)


@router.put("/preferences", response_model=NotificationPreferencesResponse)
async def update_notification_preferences(
    payload: NotificationPreferencesUpdateRequest, user: User = Depends(get_current_user)
):
    changed = payload.model_dump(exclude_unset=True)
    if "in_app" in changed:
        # An empty list is stored as an empty list, not as None: "I turned everything off"
        # must not decay back into "never chose" and re-subscribe on the next default change.
        user.notify_in_app = changed["in_app"] or []
    if "email" in changed:
        user.notify_email = changed["email"] or []
    await user.save()
    return _preferences(user)

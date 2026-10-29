"""Named webhook channels and the one place events are routed to them
(docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 9).

`route()` is called from `notification_service.notify()` and shares its contract: it never raises, and
delivery runs as a background task so a slow Teams endpoint cannot hold up the scan or request that
raised the event. A delivery failure is recorded on the channel and logged at WARNING -- never ERROR,
because ERROR is what `portal.error` alerts on and an alert must not alert about itself.
"""

import asyncio
from datetime import datetime, timezone

import httpx
import structlog
from bson import ObjectId

from app.core.notification_events import BY_KEY, EVENTS
from app.core.security import decrypt_secret
from app.models.webhook_channel import WebhookChannel
from app.models.workspace_settings import WorkspaceSettings
from app.services import alert_service

logger = structlog.get_logger(__name__)

_in_flight: set[asyncio.Task] = set()

MIGRATED_NAME = "Admin alerts"


def describe_error(exc: Exception) -> str:
    """A short reason that can never contain the webhook URL (httpx puts it in str(exc))."""
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    if isinstance(exc, ValueError):  # vet_webhook_url / resolve_vetted_ips messages name no URL
        return str(exc)[:200]
    return type(exc).__name__


def _status_of(exc: Exception) -> int | None:
    return exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None


async def record_result(channel_id, ok: bool, error: str | None) -> None:
    try:
        await WebhookChannel.get_pymongo_collection().update_one(
            {"_id": ObjectId(str(channel_id))},
            {
                "$set": {
                    "last_delivery_at": datetime.now(timezone.utc),
                    "last_status": "ok" if ok else "error",
                    "last_error": None if ok else error,
                }
            },
        )
    except Exception:
        logger.warning("webhook channel status write failed", exc_info=True)


async def send_card(channel: WebhookChannel, content: dict) -> tuple[bool, int | None, str | None]:
    """Post a ready-made card and record the outcome on the channel. Never raises."""
    try:
        status = await alert_service.post_card(decrypt_secret(channel.url_enc), content)
    except Exception as exc:
        error = describe_error(exc)
        logger.warning("webhook channel delivery failed", channel=channel.name, host=alert_service.host_of(channel.url_enc), error=error)
        await record_result(channel.id, False, error)
        return False, _status_of(exc), error
    await record_result(channel.id, True, None)
    return True, status, None


async def send_message(
    channel: WebhookChannel,
    title: str,
    text: str,
    link: str | None,
    facts: list[tuple[str, str]] | None,
    **style,
) -> tuple[bool, int | None, str | None]:
    try:
        status = await alert_service.post_webhook(decrypt_secret(channel.url_enc), title, text, link, facts, **style)
    except Exception as exc:
        error = describe_error(exc)
        logger.warning("webhook channel delivery failed", channel=channel.name, host=alert_service.host_of(channel.url_enc), error=error)
        await record_result(channel.id, False, error)
        return False, _status_of(exc), error
    await record_result(channel.id, True, None)
    return True, status, None


_BAD = ("failed", "failing", "unhealthy", "missing", "error", "stalled", "silent", "exhausted")
_WARN = ("threshold", "requested", "noisy")
_GOOD = ("completed", "decided", "proposal_created")


def tone_for(event_key: str) -> str:
    """Header colour of the card: red for something broken, amber for needs-a-look, green for done."""
    if any(w in event_key for w in _BAD):
        return "attention"
    if any(w in event_key for w in _WARN):
        return "warning"
    if any(w in event_key for w in _GOOD):
        return "good"
    return "accent"


def matches(channel: WebhookChannel, event_key: str, project_id: str | None) -> bool:
    if not channel.enabled or event_key not in channel.events:
        return False
    return not channel.project_ids or (project_id is not None and project_id in channel.project_ids)


async def route(
    event_key: str,
    *,
    project_id: str | None,
    title: str,
    body: str,
    link: str | None,
    facts: list[tuple[str, str]] | None = None,
) -> int:
    """Start delivery to every enabled channel subscribed to this event (and project). Returns how
    many deliveries were started. Never raises."""
    try:
        channels = await WebhookChannel.find(WebhookChannel.enabled == True).to_list()  # noqa: E712
        targets = [c for c in channels if matches(c, event_key, project_id)]
        if not targets:
            return 0
        style = {"tone": tone_for(event_key), "eyebrow": BY_KEY[event_key].label}
        for channel in targets:
            task = asyncio.create_task(send_message(channel, title, body, link, facts, **style))
            _in_flight.add(task)
            task.add_done_callback(_in_flight.discard)
        return len(targets)
    except Exception:
        logger.warning("webhook routing failed", event_key=event_key, exc_info=True)
        return 0


async def drain() -> None:
    """Wait for in-flight deliveries (tests, and a clean shutdown)."""
    while _in_flight:
        await asyncio.gather(*list(_in_flight), return_exceptions=True)


# --- legacy workspace webhook ---------------------------------------------------------------


def admin_event_keys() -> list[str]:
    return [e.key for e in EVENTS if e.audience == "admin"]


async def has_migrated_channel() -> bool:
    return await WebhookChannel.find_one(WebhookChannel.migrated_from_workspace == True) is not None  # noqa: E712


async def migrate_legacy_webhook() -> bool:
    """Turn WorkspaceSettings.alert_webhook_enc into the "Admin alerts" channel, subscribed to every
    admin-audience event. Idempotent: once the migrated channel exists nothing more happens, and an
    admin who later deletes or edits it is not overridden. Returns whether a channel was created."""
    if await has_migrated_channel():
        return False
    ws = await WorkspaceSettings.find_one()
    if ws is None or not ws.alert_webhook_enc:
        return False
    await WebhookChannel(
        name=MIGRATED_NAME,
        url_enc=ws.alert_webhook_enc,
        enabled=ws.alert_webhook_enabled,
        events=admin_event_keys(),
        migrated_from_workspace=True,
    ).insert()
    return True


async def sync_legacy(ws: WorkspaceSettings) -> None:
    """The old Workspace Settings > Alerts page still edits alert_webhook_enc/enabled; keep the
    migrated channel in step so that page does not silently stop working."""
    try:
        channel = await WebhookChannel.find_one(WebhookChannel.migrated_from_workspace == True)  # noqa: E712
        if channel is None:
            await migrate_legacy_webhook()
            return
        if ws.alert_webhook_enc:
            channel.url_enc = ws.alert_webhook_enc
        channel.enabled = ws.alert_webhook_enabled
        channel.updated_at = datetime.now(timezone.utc)
        await channel.save()
    except Exception:
        logger.warning("legacy webhook sync failed", exc_info=True)

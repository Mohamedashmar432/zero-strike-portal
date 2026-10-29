"""Admin CRUD for webhook channels (docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 9)."""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi import status as http_status

from app.core.deps import require_admin
from app.core.notification_events import EVENTS
from app.core.security import encrypt_secret
from app.models.user import User
from app.models.webhook_channel import WebhookChannel
from app.schemas.webhook_channel import (
    ChannelCreateRequest,
    ChannelEvent,
    ChannelResponse,
    ChannelTestResponse,
    ChannelUpdateRequest,
)
from app.services import alert_service, audit_service, webhook_channel_service

router = APIRouter(prefix="/admin/webhook-channels", tags=["admin"], dependencies=[Depends(require_admin)])

_GROUPS = {
    "scan": "Scans",
    "compliance": "Compliance",
    "autofix": "Auto-fix",
    "ai": "AI",
    "finding": "Findings",
    "scanner": "Scanner",
    "scan_engine": "Scanner",
    "pipeline": "Pipelines",
    "portal": "Portal",
    "user": "Users",
    "email": "Portal",
}


def _group(key: str) -> str:
    return _GROUPS.get(key.split(".")[0], "Other")


def _response(c: WebhookChannel) -> ChannelResponse:
    return ChannelResponse(
        id=str(c.id),
        name=c.name,
        url_host=alert_service.host_of(c.url_enc),
        enabled=c.enabled,
        events=c.events,
        project_ids=c.project_ids,
        include_digest=c.include_digest,
        last_delivery_at=c.last_delivery_at,
        last_status=c.last_status,
        last_error=c.last_error,
        created_at=c.created_at,
    )


async def _encrypt_vetted(url: str) -> str:
    try:
        return encrypt_secret(await asyncio.to_thread(alert_service.vet_webhook_url, url))
    except ValueError as exc:
        raise HTTPException(http_status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


async def _get_or_404(channel_id: str) -> WebhookChannel:
    channel = await WebhookChannel.get(channel_id)
    if channel is None:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, "Webhook channel not found")
    return channel


async def _audit(action: str, admin: User, channel: WebhookChannel, **extra) -> None:
    # Never the URL: the name, the host and what changed.
    await audit_service.record(
        action,
        actor_user_id=str(admin.id),
        target_type="webhook_channel",
        target_id=str(channel.id),
        metadata={"name": channel.name, "host": alert_service.host_of(channel.url_enc), **extra},
    )


@router.get("/events", response_model=list[ChannelEvent])
async def list_events():
    return [
        ChannelEvent(key=e.key, label=e.label, description=e.description, audience=e.audience, group=_group(e.key))
        for e in EVENTS
    ]


@router.get("", response_model=list[ChannelResponse])
async def list_channels():
    return [_response(c) for c in await WebhookChannel.find_all().sort("created_at").to_list()]


@router.post("", response_model=ChannelResponse, status_code=http_status.HTTP_201_CREATED)
async def create_channel(payload: ChannelCreateRequest, admin: User = Depends(require_admin)):
    channel = WebhookChannel(
        name=payload.name.strip(),
        url_enc=await _encrypt_vetted(payload.url),
        enabled=payload.enabled,
        events=payload.events,
        project_ids=payload.project_ids,
        include_digest=payload.include_digest,
    )
    await channel.insert()
    await _audit("Webhook Channel Created", admin, channel, events=len(channel.events))
    return _response(channel)


@router.patch("/{channel_id}", response_model=ChannelResponse)
async def update_channel(channel_id: str, payload: ChannelUpdateRequest, admin: User = Depends(require_admin)):
    channel = await _get_or_404(channel_id)
    changed = payload.model_dump(exclude_unset=True)
    url = changed.pop("url", None)
    if url is not None:
        channel.url_enc = await _encrypt_vetted(url)
    for field, value in changed.items():
        if value is not None:
            setattr(channel, field, value.strip() if field == "name" else value)
    channel.updated_at = datetime.now(timezone.utc)
    await channel.save()
    fields = sorted([*changed, *(["url"] if url is not None else [])])
    await _audit("Webhook Channel Updated", admin, channel, fields=fields)
    return _response(channel)


@router.delete("/{channel_id}", status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_id: str, admin: User = Depends(require_admin)):
    channel = await _get_or_404(channel_id)
    await channel.delete()
    await _audit("Webhook Channel Deleted", admin, channel)


@router.post("/{channel_id}/test", response_model=ChannelTestResponse)
async def test_channel(channel_id: str, admin: User = Depends(require_admin)):
    channel = await _get_or_404(channel_id)
    ok, status, error = await webhook_channel_service.send_message(
        channel,
        "thinkShield: test message",
        f'This is a test message for the webhook channel "{channel.name}".',
        "/admin/control-panel",
        None,
    )
    await _audit("Webhook Channel Tested", admin, channel, ok=ok)
    return ChannelTestResponse(ok=ok, status=status, error=error)

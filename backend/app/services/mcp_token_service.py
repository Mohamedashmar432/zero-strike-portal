"""Admin MCP credentials: issue, list, revoke, and resolve a raw token to its (admin) owner."""

import secrets
from datetime import datetime, timedelta, timezone

from app.core import security
from app.models.mcp_token import McpToken
from app.models.user import User

TOKEN_PREFIX = "tsmcp_"
MAX_TTL_DAYS = 90
# Same coarse last-used window as api_key_service: one write per token per minute, not per call.
_LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_active(token: McpToken) -> bool:
    return token.revoked_at is None and _aware(token.expires_at) > datetime.now(timezone.utc)


async def issue(user: User, label: str, expires_in_days: int) -> tuple[McpToken, str]:
    """Returns (token document, raw token). The raw token exists only in this return value."""
    raw = f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"
    now = datetime.now(timezone.utc)
    token = McpToken(
        user_id=str(user.id),
        label=label,
        prefix=raw[:12],
        key_hash=security.hash_token(raw),
        created_at=now,
        expires_at=now + timedelta(days=min(expires_in_days, MAX_TTL_DAYS)),
    )
    await token.insert()
    return token, raw


async def list_for_user(user: User) -> list[McpToken]:
    return await McpToken.find(McpToken.user_id == str(user.id)).sort("-created_at").to_list()


async def rename(user: User, token_id: str, label: str) -> McpToken | None:
    """Relabel one of the caller's own tokens. The secret, expiry and revocation are untouched."""
    token = await McpToken.get(token_id)
    if not token or token.user_id != str(user.id):
        return None
    token.label = label
    await token.save()
    return token


async def revoke(user: User, token_id: str) -> McpToken | None:
    """Revoke one of the caller's own tokens. None when it does not exist or is not theirs."""
    token = await McpToken.get(token_id)
    if not token or token.user_id != str(user.id):
        return None
    if token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        await token.save()
    return token


async def resolve(raw: str, ip: str | None = None) -> tuple[McpToken, User] | None:
    """The active token and its owner for a raw credential, else None. Does NOT check the owner's
    role — the caller decides between 401 (no such credential) and 403 (credential fine, owner not
    an admin any more)."""
    token = await McpToken.find_one(McpToken.key_hash == security.hash_token(raw))
    if not token or not is_active(token):
        return None
    user = await User.get(token.user_id)
    if not user:
        return None
    now = datetime.now(timezone.utc)
    if token.last_used_at is None or now - _aware(token.last_used_at) >= _LAST_USED_WRITE_INTERVAL:
        token.last_used_at = now
        token.last_used_ip = ip
        await token.save()
    return token, user

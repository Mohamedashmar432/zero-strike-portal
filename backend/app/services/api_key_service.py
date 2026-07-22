"""API key validation shared by the /apikeys/validate endpoint and the
scanner-facing api-key auth dependency (deps.get_api_key_context), so the two
never drift.
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status

from app.core import security
from app.models.api_key import ApiKey

# ponytail: coarse last-used resolution — one write at most per this window per key, not per
# request. Widen if per-request last-used timestamps are ever needed.
_LAST_USED_WRITE_INTERVAL = timedelta(seconds=60)


def is_active(key: ApiKey) -> bool:
    return (
        key.revoked_at is None
        and key.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
    )


async def resolve_api_key(raw_token: str, request: Request | None = None) -> ApiKey:
    """Return the active ApiKey for a raw token, updating last-used metadata.

    Raises 401 (same generic message for missing/revoked/expired) so callers —
    the validate endpoint and the scanner auth dependency — behave identically
    and the scanner fails fast without leaking which check failed.
    """
    key = await ApiKey.find_one(ApiKey.key_hash == security.hash_token(raw_token))
    if not key or not is_active(key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired API key")
    now = datetime.now(timezone.utc)
    # Skip the write on rapid repeat calls — the scanner hits this on every request, and a write
    # per request is pure amplification when last_used only needs coarse recency.
    last = key.last_used_at
    if last is None or now - last.replace(tzinfo=timezone.utc) >= _LAST_USED_WRITE_INTERVAL:
        key.last_used_at = now
        key.last_used_ip = request.client.host if request and request.client else None
        await key.save()
    return key

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

_BCRYPT_MAX_BYTES = 72  # bcrypt silently ignores/rejects input beyond this


def hash_password(password: str) -> str:
    truncated = password.encode()[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    truncated = password.encode()[:_BCRYPT_MAX_BYTES]
    return bcrypt.checkpw(truncated, password_hash.encode())


def _encode(claims: dict) -> str:
    return jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user_id,
        "role": role,
        "jti": str(uuid.uuid4()),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
        "type": "access",
    }
    return _encode(claims)


def create_refresh_token(user_id: str) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at) — caller persists jti/hash on the user document."""
    now = datetime.now(timezone.utc)
    jti = str(uuid.uuid4())
    expires_at = now + timedelta(days=settings.refresh_token_ttl_days)
    claims = {"sub": user_id, "jti": jti, "iat": now, "exp": expires_at, "type": "refresh"}
    return _encode(claims), jti, expires_at


def decode_token(token: str) -> dict:
    """Raises jose.JWTError on invalid/expired token — caller translates to 401."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def hash_token(raw: str) -> str:
    """Used for both refresh tokens and API keys — sha256 hex, never store the raw value."""
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_token, prefix_for_display, sha256_hash) — raw_token is shown to the user exactly once."""
    raw = f"zst_live_{secrets.token_urlsafe(32)}"
    prefix = raw[:12]
    return raw, prefix, hash_token(raw)


__all__ = [
    "JWTError",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_token",
    "generate_api_key",
]

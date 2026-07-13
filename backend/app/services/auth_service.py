import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.core import security
from app.core.config import settings
from app.models.project_member import ProjectMember
from app.models.user import RefreshTokenRecord, User
from app.services import email_service

logger = logging.getLogger(__name__)


class AuthError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def register(email: str, password: str, name: str) -> User:
    if await User.find_one(User.email == email):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Email already registered")
    now = datetime.now(timezone.utc)
    user = User(
        email=email,
        password_hash=security.hash_password(password),
        name=name,
        created_at=now,
        updated_at=now,
    )
    await user.insert()

    pending = await ProjectMember.find(
        ProjectMember.invited_email == email, ProjectMember.user_id == None  # noqa: E711
    ).to_list()
    for member in pending:
        member.user_id = str(user.id)
        member.accepted_at = now
        await member.save()

    return user


async def authenticate(email: str, password: str) -> User:
    user = await User.find_one(User.email == email)
    if not user or not security.verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    if not user.is_active:
        raise AuthError("Account is disabled")
    return user


def _prune_refresh_tokens(user: User) -> None:
    """Drop old revoked/expired refresh-token records so the list doesn't grow forever.

    Keeps any record that is still active (unrevoked and unexpired) regardless of age;
    only drops records that are revoked or expired AND older than the retention cutoff.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.refresh_token_retention_days)

    def _keep(record: RefreshTokenRecord) -> bool:
        if record.revoked_at is not None and record.revoked_at.replace(tzinfo=timezone.utc) < cutoff:
            return False
        if record.expires_at.replace(tzinfo=timezone.utc) < cutoff:
            return False
        return True

    user.refresh_tokens = [r for r in user.refresh_tokens if _keep(r)]


def _revoke_all_refresh_tokens(user: User, now: datetime) -> None:
    """Revoke (never delete) every not-yet-revoked refresh token record on `user`.

    Shared by the reuse-detected branch of refresh_token_pair and the
    change_password/reset_password "invalidate all sessions" step.
    """
    for record in user.refresh_tokens:
        record.revoked_at = record.revoked_at or now


async def issue_token_pair(
    user: User, *, user_agent: str | None = None, ip: str | None = None
) -> tuple[str, str, int]:
    _prune_refresh_tokens(user)
    access_token = security.create_access_token(str(user.id), user.role)
    refresh_token, jti, expires_at = security.create_refresh_token(str(user.id))
    user.refresh_tokens.append(
        RefreshTokenRecord(
            jti=jti,
            token_hash=security.hash_token(refresh_token),
            issued_at=datetime.now(timezone.utc),
            expires_at=expires_at,
            user_agent=user_agent,
            ip=ip,
        )
    )
    await user.save()
    return access_token, refresh_token, settings.access_token_ttl_minutes * 60


async def refresh_token_pair(
    refresh_token: str, *, user_agent: str | None = None, ip: str | None = None
) -> tuple[str, str, int]:
    try:
        claims = security.decode_token(refresh_token)
    except security.JWTError:
        raise AuthError("Invalid refresh token")
    if claims.get("type") != "refresh":
        raise AuthError("Invalid refresh token")

    user = await User.get(claims["sub"])
    if not user:
        raise AuthError("Invalid refresh token")

    presented_hash = security.hash_token(refresh_token)
    record = next((r for r in user.refresh_tokens if r.jti == claims["jti"]), None)
    if record is None or record.token_hash != presented_hash:
        raise AuthError("Invalid refresh token")

    if record.revoked_at is not None:
        # Reuse of an already-rotated token: treat as theft, revoke everything.
        _revoke_all_refresh_tokens(user, datetime.now(timezone.utc))
        await user.save()
        raise AuthError("Refresh token reuse detected — all sessions revoked")

    if record.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise AuthError("Refresh token expired")

    record.revoked_at = datetime.now(timezone.utc)
    return await issue_token_pair(user, user_agent=user_agent, ip=ip)


async def logout(refresh_token: str) -> str | None:
    """Returns the user id that was logged out, or None if the token was already invalid."""
    try:
        claims = security.decode_token(refresh_token)
    except security.JWTError:
        return None
    user = await User.get(claims.get("sub", ""))
    if not user:
        return None
    record = next((r for r in user.refresh_tokens if r.jti == claims.get("jti")), None)
    if record and record.revoked_at is None:
        record.revoked_at = datetime.now(timezone.utc)
        await user.save()
    return str(user.id)


async def change_password(user: User, current_password: str, new_password: str) -> None:
    """Verify the current password, set the new one, and revoke every existing session.

    Revoking all refresh tokens forces re-authentication everywhere else the account is
    logged in — the same treatment as a detected refresh-token-reuse (theft) event, since a
    password change is exactly the point a compromised session should be kicked out.
    """
    if not security.verify_password(current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")

    now = datetime.now(timezone.utc)
    user.password_hash = security.hash_password(new_password)
    _revoke_all_refresh_tokens(user, now)
    user.updated_at = now
    await user.save()


async def request_password_reset(email: str) -> None:
    """Anti-enumeration: always returns silently regardless of whether the email exists/is active.

    Callers (the router) must always show the same generic success message no matter what
    this function does internally.
    """
    user = await User.find_one(User.email == email)
    if user is None or not user.is_active:
        return

    raw, token_hash = security.generate_reset_token()
    user.password_reset_token_hash = token_hash
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
        minutes=settings.password_reset_token_ttl_minutes
    )
    await user.save()

    reset_url = f"{settings.frontend_origin}/reset-password?token={raw}"
    try:
        await asyncio.to_thread(
            email_service.send_password_reset_email,
            user.email,
            reset_url,
            settings.password_reset_token_ttl_minutes,
        )
    except Exception:
        logger.exception("Failed to send password reset email to %s", user.email)


async def reset_password(token: str, new_password: str) -> User:
    """Consume a password-reset token: verify it, set the new password, and revoke all sessions.

    Single-use by construction — both password_reset_token_hash and password_reset_expires_at
    are cleared on success, so a second attempt with the same token always falls into the
    "invalid or expired" branch below. Returns the affected user so the caller (the router) can
    record an audit log entry for this account-recovery event.
    """
    token_hash = security.hash_token(token)
    user = await User.find_one(User.password_reset_token_hash == token_hash)

    if (
        user is None
        or user.password_reset_expires_at is None
        or user.password_reset_expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired reset token")

    now = datetime.now(timezone.utc)
    user.password_hash = security.hash_password(new_password)
    user.password_reset_token_hash = None
    user.password_reset_expires_at = None
    _revoke_all_refresh_tokens(user, now)
    user.updated_at = now
    await user.save()
    return user

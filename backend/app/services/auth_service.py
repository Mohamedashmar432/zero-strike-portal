from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.core import security
from app.core.config import settings
from app.models.project_member import ProjectMember
from app.models.user import RefreshTokenRecord, User


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


async def issue_token_pair(
    user: User, *, user_agent: str | None = None, ip: str | None = None
) -> tuple[str, str, int]:
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
        now = datetime.now(timezone.utc)
        for r in user.refresh_tokens:
            r.revoked_at = r.revoked_at or now
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

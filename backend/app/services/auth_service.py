import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import BackgroundTasks, HTTPException, status

from app.core import email_templates, security
from app.core.config import settings
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.user import RefreshTokenRecord, User
from app.services import audit_service, email_service, notification_service, workspace_settings_service

logger = structlog.get_logger(__name__)


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
        approval_status="pending" if await _approval_required() else "approved",
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


async def _approval_required() -> bool:
    """Signup approval is on AND there is an admin who can grant it.

    Without the second condition the first registration on a fresh deployment would create a
    pending account with nobody able to approve it, and the portal could never be bootstrapped.
    """
    ws = await workspace_settings_service.get_workspace_settings()
    if not ws.signup_requires_approval:
        return False
    return await User.find_one(
        User.role == "admin", User.is_active == True, User.approval_status == "approved"  # noqa: E712
    ) is not None


PENDING_MESSAGE = (
    "Your account is awaiting administrator approval. "
    "You will receive an email once your access has been reviewed."
)
REJECTED_MESSAGE = (
    "Your access request was not approved. Please contact your administrator for assistance."
)


def approval_block(user: User) -> HTTPException | None:
    """The 403 to raise for an account that has not been approved, or None if it has."""
    if user.approval_status == "pending":
        return HTTPException(status.HTTP_403_FORBIDDEN, PENDING_MESSAGE)
    if user.approval_status == "rejected":
        return HTTPException(status.HTTP_403_FORBIDDEN, REJECTED_MESSAGE)
    return None


async def authenticate(email: str, password: str) -> User:
    user = await User.find_one(User.email == email)
    if not user or not security.verify_password(password, user.password_hash):
        raise AuthError("Invalid email or password")
    if not user.is_active:
        raise AuthError("Account is disabled")
    # After the password check, so the status is only ever shown to someone who knows the
    # password and a stranger cannot probe which addresses are awaiting approval.
    if (blocked := approval_block(user)) is not None:
        raise blocked
    return user


# --- signup approval ---------------------------------------------------------


async def _send_template(
    to: str, key: str, values: dict[str, str], context: str = "signup decision"
) -> None:
    """Send one templated email. Never raises: the approval decision is already saved."""
    try:
        ws = await workspace_settings_service.get_workspace_settings()
        subject, text, html = email_templates.render(key, ws.email_templates, values)
        await asyncio.to_thread(email_service.send_email, to, subject, text, html)
    except Exception:
        logger.exception("signup email failed", template=key)
        await notification_service.report_email_failure(context)


async def send_welcome_email(user: User) -> None:
    """Welcome an open-signup (auto-approved) user. Run as a background task; never raises."""
    await _send_template(
        user.email,
        "signup_welcome",
        {"name": user.name, "action_url": f"{settings.frontend_origin}/login"},
        context="welcome",
    )


async def send_project_invite(email: str, inviter: str, project: Project, existing: bool) -> None:
    """Tell the invitee about a project invite. An existing account already has access, so the
    link opens the project; otherwise it goes to registration, which picks up the pending
    membership (see `register`). Run as a background task; never raises."""
    origin = settings.frontend_origin
    await _send_template(
        email,
        "project_invite_existing" if existing else "project_invite_new",
        {
            "inviter": inviter,
            "project": project.name,
            "action_url": f"{origin}/projects/{project.id}" if existing else f"{origin}/register",
        },
        context="project invite",
    )


async def announce_signup(user: User) -> None:
    """Tell the chosen reviewers a signup is waiting. Falls back to every active admin when
    no reviewers are chosen (or the chosen ones are gone), so a request is never unseen."""
    ws = await workspace_settings_service.get_workspace_settings()
    chosen = set(ws.signup_notify_admin_ids)
    admins = await User.find(User.role == "admin", User.is_active == True).to_list()  # noqa: E712
    reviewers = [str(a.id) for a in admins if str(a.id) in chosen]
    url = f"{settings.frontend_origin}/admin/users?status=pending"
    subject, text, html = email_templates.render(
        "signup_requested",
        ws.email_templates,
        {"name": user.name, "email": user.email, "action_url": url},
    )
    await notification_service.notify(
        "user.signup_requested",
        title=f"Access request from {user.name}",
        body=f"{user.name} ({user.email}) is waiting for approval.",
        link="/admin/users?status=pending",
        severity="warning",
        only_user_ids=reviewers or None,
        email_message=(subject, text, html),
    )


async def approve_user(user: User) -> bool:
    """pending/rejected -> approved. Returns False (and sends nothing) if already approved,
    so a double click cannot email the applicant twice."""
    if user.approval_status == "approved":
        return False
    user.approval_status = "approved"
    user.rejection_reason = None
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    return True


async def reject_user(user: User, reason: str | None) -> bool:
    """pending -> rejected. Returns False if it was already rejected (idempotent)."""
    if user.approval_status == "rejected":
        return False
    user.approval_status = "rejected"
    user.rejection_reason = reason or None
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    return True


async def send_decision_email(user: User) -> None:
    """Email the applicant the outcome. Run as a background task: an SMTP handshake can take
    many seconds and the admin's click must not wait on it."""
    if user.approval_status == "approved":
        await _send_template(
            user.email,
            "signup_approved",
            {"name": user.name, "action_url": f"{settings.frontend_origin}/login"},
        )
    else:
        reason = user.rejection_reason
        await _send_template(
            user.email,
            "signup_rejected",
            {"name": user.name, "reason": f"Reason: {reason}" if reason else ""},
        )


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


async def request_password_reset(email: str, background: BackgroundTasks) -> None:
    """Anti-enumeration: always returns silently regardless of whether the email exists/is active.

    Callers (the router) must always show the same generic success message no matter what
    this function does internally. The token write and SMTP send run after the response, so a
    known address does not take measurably longer than an unknown one.
    """
    user = await User.find_one(User.email == email)
    if user is None or not user.is_active:
        # No email stored: the address belongs to whoever typed it, not to an account.
        await audit_service.record("Password Reset Requested For Unknown Account", actor_type="anonymous")
        return
    await audit_service.record(
        "Password Reset Requested",
        actor_user_id=str(user.id),
        target_type="user",
        target_id=str(user.id),
    )
    background.add_task(_issue_and_send_reset, user)


async def _issue_and_send_reset(user: User) -> None:
    try:
        raw, token_hash = security.generate_reset_token()
        user.password_reset_token_hash = token_hash
        user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.password_reset_token_ttl_minutes
        )
        await user.save()

        reset_url = f"{settings.frontend_origin}/reset-password?token={raw}"
        await asyncio.to_thread(
            email_service.send_password_reset_email,
            user.email,
            reset_url,
            settings.password_reset_token_ttl_minutes,
        )
    except Exception as exc:
        logger.exception("Failed to send password reset email", user_id=str(user.id))
        await audit_service.record(
            "Password Reset Email Failed",
            actor_type="system",
            target_id=str(user.id),
            metadata={"error": type(exc).__name__},
        )
        await notification_service.report_email_failure("password reset")


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

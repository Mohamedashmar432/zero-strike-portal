"""Notification fan-out: resolve recipients, honour their preferences, deliver in-app and
by email.

The one rule that shapes this module: **notifying must never break the thing that was being
notified about.** A scan that produced a valid report has completed whether or not anyone
could be told. Every public entry point therefore catches its own exceptions and logs them;
nothing here raises into a caller.

Email goes through the existing `email_service`, which no-ops with a warning when
`settings.smtp_host` is unset — the default in every environment today. Email delivery is
wired and inert rather than absent, so configuring SMTP is the only step needed to turn it on.
"""

import asyncio
from datetime import datetime, timezone

import structlog
from beanie import PydanticObjectId
from beanie.operators import In

from app.core.notification_events import BY_KEY, DEFAULT_EMAIL, DEFAULT_IN_APP
from app.models.notification import Notification, NotificationSeverity
from app.models.project_member import ProjectMember
from app.models.user import User
from app.services import email_service

logger = structlog.get_logger(__name__)

# asyncio holds only a weak reference to a running task, so a bare create_task() can be
# garbage-collected mid-send. Same guard the queue services use.
_in_flight: set[asyncio.Task] = set()


def wants(user: User, event_key: str, channel: str) -> bool:
    """Whether `user` has this event switched on for this channel.

    `None` on the user means they never touched their preferences, so the catalog default
    applies. An explicit empty list means they turned everything off and must stay off.
    """
    if channel == "email":
        chosen = user.notify_email if user.notify_email is not None else DEFAULT_EMAIL
    else:
        chosen = user.notify_in_app if user.notify_in_app is not None else DEFAULT_IN_APP
    return event_key in chosen


async def _recipients(event_key: str, project_id: str | None) -> list[User]:
    """Who is eligible for this event, before per-user preferences are applied."""
    event = BY_KEY[event_key]
    if event.audience == "admin":
        return await User.find(User.role == "admin", User.is_active == True).to_list()  # noqa: E712

    if project_id is None:
        return []
    members = await ProjectMember.find(ProjectMember.project_id == project_id).to_list()
    # Invited-but-unaccepted members have no user_id yet; an id that no longer parses belongs
    # to a deleted user. Both are skipped rather than producing undeliverable rows.
    object_ids = []
    for member in members:
        if not member.user_id:
            continue
        try:
            object_ids.append(PydanticObjectId(member.user_id))
        except Exception:
            continue
    if not object_ids:
        return []
    return await User.find(In(User.id, object_ids), User.is_active == True).to_list()  # noqa: E712


async def notify(
    event_key: str,
    *,
    project_id: str | None = None,
    title: str,
    body: str = "",
    link: str | None = None,
    severity: NotificationSeverity = "info",
) -> int:
    """Deliver one event to everyone eligible who wants it. Returns the in-app row count.

    Never raises. An unknown event key is a programming error and is logged as one rather
    than thrown, because the alternative is a background task dying on a typo in a string.
    """
    try:
        if event_key not in BY_KEY:
            logger.error("unknown notification event", event_key=event_key)
            return 0

        users = await _recipients(event_key, project_id)
        if not users:
            return 0

        rows = [
            Notification(
                user_id=str(u.id),
                event=event_key,
                title=title,
                body=body,
                severity=severity,
                project_id=project_id,
                link=link,
            )
            for u in users
            if wants(u, event_key, "in_app")
        ]
        if rows:
            await Notification.insert_many(rows)

        email_targets = [u.email for u in users if wants(u, event_key, "email")]
        if email_targets:
            # smtplib is blocking; the whole batch goes to one worker thread so a slow or
            # unreachable SMTP host cannot stall the event loop.
            task = asyncio.create_task(_send_emails(email_targets, title, body, link))
            _in_flight.add(task)
            task.add_done_callback(_in_flight.discard)

        return len(rows)
    except Exception:
        logger.exception("notification delivery failed", event_key=event_key, project_id=project_id)
        return 0


async def _send_emails(addresses: list[str], title: str, body: str, link: str | None) -> None:
    def _send() -> None:
        text = body or title
        if link:
            text = f"{text}\n\n{link}"
        for address in addresses:
            try:
                email_service.send_email(address, f"[ZeroStrike] {title}", text)
            except Exception:
                logger.warning("notification email failed", to=address, exc_info=True)

    try:
        await asyncio.to_thread(_send)
    except Exception:
        logger.exception("notification email batch failed")


# --- read side ---------------------------------------------------------------


async def list_for_user(user_id: str, *, limit: int = 50) -> list[Notification]:
    return (
        await Notification.find(Notification.user_id == user_id)
        .sort("-created_at")
        .limit(limit)
        .to_list()
    )


async def unread_count(user_id: str) -> int:
    return await Notification.find(
        Notification.user_id == user_id, Notification.read_at == None  # noqa: E711
    ).count()


async def mark_read(user_id: str, notification_id: str | None) -> int:
    """Mark one notification read, or every unread one when `notification_id` is None.

    The single-id path re-checks user_id rather than trusting the id, so a guessed or
    leaked id cannot mark someone else's notification read.
    """
    now = datetime.now(timezone.utc)
    if notification_id is not None:
        row = await Notification.get(notification_id)
        if row is None or row.user_id != user_id or row.read_at is not None:
            return 0
        row.read_at = now
        await row.save()
        return 1

    rows = await Notification.find(
        Notification.user_id == user_id, Notification.read_at == None  # noqa: E711
    ).to_list()
    for row in rows:
        row.read_at = now
        await row.save()
    return len(rows)

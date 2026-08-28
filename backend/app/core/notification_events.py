"""The notification event catalog.

Every event a user can subscribe to is declared here once, and nothing may be notified that
is not in this table — `notification_service.notify` raises on an unknown key. That keeps the
preferences UI, the delivery path, and the emission sites from drifting apart, which is the
usual way a notification system ends up with switches that control nothing.

`audience` decides who can receive an event at all, before per-user preferences are applied:

- "project" — every member of the project the event names.
- "admin"   — portal admins only. Spend, quota and infrastructure events: these are decisions
              a project member cannot act on, and quota requests name a requester, so
              broadcasting them to the project would leak one team's asks to another.
"""

from dataclasses import dataclass
from typing import Literal

Audience = Literal["project", "admin"]


@dataclass(frozen=True)
class NotificationEvent:
    key: str
    label: str
    description: str
    audience: Audience
    # Whether a brand-new user is subscribed to this by default. Kept deliberately narrow:
    # a notification system whose defaults are "everything" trains people to ignore it.
    default_in_app: bool = True
    default_email: bool = False


EVENTS: tuple[NotificationEvent, ...] = (
    NotificationEvent(
        key="scan.completed",
        label="Scan completed",
        description="A scan finished and its findings are available.",
        audience="project",
    ),
    NotificationEvent(
        key="scan.failed",
        label="Scan failed",
        description="A scan could not complete — clone, scanner or timeout failure.",
        audience="project",
        default_email=True,
    ),
    NotificationEvent(
        key="compliance.audit_completed",
        label="Compliance audit completed",
        description="An audit finished. Says how many controls failed.",
        audience="project",
    ),
    NotificationEvent(
        key="compliance.controls_failing",
        label="Compliance controls failing",
        description="An audit finished with one or more failing controls.",
        audience="project",
        default_email=True,
    ),
    NotificationEvent(
        key="autofix.proposal_created",
        label="Auto-fix proposal ready",
        description="An AI fix proposal is waiting for review.",
        audience="project",
    ),
    NotificationEvent(
        key="autofix.apply_failed",
        label="Auto-fix apply failed",
        description="An approved fix could not be applied or its re-scan blocked the PR.",
        audience="project",
        default_email=True,
    ),
    NotificationEvent(
        key="autofix.quota_exhausted",
        label="Auto-fix allowance exhausted",
        description="A scan used its full auto-fix allowance.",
        audience="project",
    ),
    NotificationEvent(
        key="autofix.quota_requested",
        label="Auto-fix allowance requested",
        description="Someone asked for extra auto-fix headroom and is waiting on a decision.",
        audience="admin",
        default_email=True,
    ),
    NotificationEvent(
        key="scanner.unhealthy",
        label="Scanner unhealthy",
        description="The scanner binary is missing or failing to run.",
        audience="admin",
        default_email=True,
    ),
)

BY_KEY = {e.key: e for e in EVENTS}
EVENT_KEYS = frozenset(BY_KEY)

DEFAULT_IN_APP = [e.key for e in EVENTS if e.default_in_app]
DEFAULT_EMAIL = [e.key for e in EVENTS if e.default_email]


def visible_events(*, is_admin: bool) -> tuple[NotificationEvent, ...]:
    """The events this principal can actually receive.

    An admin-audience event is never delivered to a non-admin, so offering them the switch —
    or handing them a default subscription to it — would be a control that does nothing.
    Filtering here rather than in the UI keeps the event list and the two channel lists
    consistent by construction, so a non-admin pressing Save cannot persist a subscription
    to something they will never be sent.
    """
    return tuple(e for e in EVENTS if is_admin or e.audience != "admin")


def defaults_for(*, is_admin: bool, channel: str) -> list[str]:
    return [
        e.key
        for e in visible_events(is_admin=is_admin)
        if (e.default_email if channel == "email" else e.default_in_app)
    ]

from datetime import datetime

from pydantic import BaseModel

from app.schemas.common import Page


class AuditLogResponse(BaseModel):
    id: str
    actor_type: str
    actor_user_id: str | None
    #: Resolved from actor_user_id. An audit trail that shows raw ObjectIds is one nobody
    #: reads; None when the actor was the system, an API key, or a since-deleted user.
    actor_email: str | None = None
    action: str
    #: Which bucket this row falls in — see audit_service.classify.
    category: str
    target_type: str | None
    target_id: str | None
    project_id: str | None
    project_name: str | None = None
    metadata: dict
    ip_address: str | None
    created_at: datetime


class AuditLogCounts(BaseModel):
    """Counts over the whole requested window, not just the returned page."""

    total: int
    admin: int
    project: int
    privilege: int
    #: Cross-cutting: rows whose action records a failure. Overlaps the three above.
    failed: int


class AuditLogPage(Page):
    counts: AuditLogCounts
    window_days: int

from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, Query

from app.core.deps import require_admin
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.user import User
from app.schemas.audit_log import AuditLogCounts, AuditLogPage, AuditLogResponse
from app.services import audit_service

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"], dependencies=[Depends(require_admin)])


def _to_response(
    log: AuditLog, actors: dict[str, str], projects: dict[str, str]
) -> AuditLogResponse:
    return AuditLogResponse(
        id=str(log.id),
        actor_type=log.actor_type,
        actor_user_id=log.actor_user_id,
        actor_email=actors.get(log.actor_user_id or ""),
        action=log.action,
        category=audit_service.classify(log.action, log.project_id),
        target_type=log.target_type,
        target_id=log.target_id,
        project_id=log.project_id,
        project_name=projects.get(log.project_id or ""),
        metadata=log.metadata,
        ip_address=log.ip_address,
        created_at=log.created_at,
    )


async def _label_map(model, ids: set[str], field: str) -> dict[str, str]:
    """id -> human label for the ids on one page. Two extra queries per request beats
    rendering raw ObjectIds, which is what an unreadable audit trail looks like."""
    valid = [PydanticObjectId(i) for i in ids if PydanticObjectId.is_valid(i)]
    if not valid:
        return {}
    docs = await model.find(In(model.id, valid)).to_list()
    return {str(d.id): getattr(d, field) for d in docs}


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    days: int = Query(1, ge=1, le=90, description="Window, in days back from now."),
    category: str | None = Query(None, description="privilege | project | admin | failed"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    """One window of the audit trail, plus per-category counts over that whole window.

    The window defaults to the last day: that is the read someone actually wants when they
    open this page, and it keeps the in-memory classification below honest.

    ponytail: the window is loaded into memory and categorised in Python, because the
    category is derived from the action string and Mongo cannot $group on something it does
    not store. Fine at a day; if the window ever needs to span months, store a `category` on
    write and aggregate server-side.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    window = await AuditLog.find(AuditLog.created_at >= since).sort(-AuditLog.created_at).to_list()

    counts = AuditLogCounts(
        total=len(window),
        admin=sum(1 for log in window if audit_service.classify(log.action, log.project_id) == "admin"),
        project=sum(
            1 for log in window if audit_service.classify(log.action, log.project_id) == "project"
        ),
        privilege=sum(
            1 for log in window if audit_service.classify(log.action, log.project_id) == "privilege"
        ),
        failed=sum(1 for log in window if audit_service.is_failure(log.action)),
    )

    if category == "failed":
        matching = [log for log in window if audit_service.is_failure(log.action)]
    elif category in audit_service.CATEGORIES:
        matching = [
            log for log in window if audit_service.classify(log.action, log.project_id) == category
        ]
    else:
        matching = window

    items = matching[(page - 1) * page_size : page * page_size]
    actors = await _label_map(User, {log.actor_user_id for log in items if log.actor_user_id}, "email")
    projects = await _label_map(Project, {log.project_id for log in items if log.project_id}, "name")

    return AuditLogPage(
        items=[_to_response(log, actors, projects) for log in items],
        total=len(matching),
        page=page,
        page_size=page_size,
        counts=counts,
        window_days=days,
    )

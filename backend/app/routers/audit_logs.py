from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.deps import require_admin
from app.core.timeutils import as_utc
from app.models.audit_log import AuditLog
from app.models.project import Project
from app.models.system_log import SystemLog
from app.models.user import User
from app.schemas.audit_log import (
    AuditLogCounts,
    AuditLogPage,
    AuditLogResponse,
    SystemLogPage,
    SystemLogResponse,
)
from app.services import audit_service

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"], dependencies=[Depends(require_admin)])


def _to_response(
    log: AuditLog, actors: dict[str, str], projects: dict[str, str]
) -> AuditLogResponse:
    project_id = audit_service.effective_project_id(log)
    return AuditLogResponse(
        id=str(log.id),
        actor_type=log.actor_type,
        actor_user_id=log.actor_user_id,
        actor_email=actors.get(log.actor_user_id or ""),
        action=log.action,
        category=audit_service.classify(log.action, audit_service.effective_project_id(log)),
        target_type=log.target_type,
        target_id=log.target_id,
        project_id=project_id,
        project_name=projects.get(project_id or ""),
        metadata=log.metadata,
        ip_address=log.ip_address,
        created_at=as_utc(log.created_at),
    )


async def _label_map(model, ids: set[str], field: str) -> dict[str, str]:
    """id -> human label for the ids on one page. Two extra queries per request beats
    rendering raw ObjectIds, which is what an unreadable audit trail looks like."""
    valid = [PydanticObjectId(i) for i in ids if PydanticObjectId.is_valid(i)]
    if not valid:
        return {}
    docs = await model.find(In(model.id, valid)).to_list()
    return {str(d.id): getattr(d, field) for d in docs}


_MAX_RANGE = timedelta(days=92)


def _window(days: int, since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    """[since, until) in UTC. An explicit range comes from the page's date pickers, already
    converted from the admin's local midnight; `days` is the older last-N-days form."""
    now = datetime.now(timezone.utc)
    if since is None:
        return now - timedelta(days=days), now
    since = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
    until = (until if until.tzinfo else until.replace(tzinfo=timezone.utc)) if until else now
    if until <= since:
        raise HTTPException(422, "The end of the range must be after its start.")
    # The audit window is loaded into memory (see list_audit_logs), so its span stays bounded.
    if until - since > _MAX_RANGE:
        raise HTTPException(422, "A date range can span at most 92 days.")
    return since, until


@router.get("", response_model=AuditLogPage)
async def list_audit_logs(
    days: int = Query(1, ge=1, le=90, description="Window, in days back from now."),
    since: datetime | None = Query(None, description="Range start; overrides `days`."),
    until: datetime | None = Query(None, description="Range end (default now); with `since`."),
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
    since, until = _window(days, since, until)
    window = (
        await AuditLog.find(AuditLog.created_at >= since, AuditLog.created_at < until)
        .sort(-AuditLog.created_at)
        .to_list()
    )

    counts = AuditLogCounts(
        total=len(window),
        admin=sum(1 for log in window if audit_service.classify(log.action, audit_service.effective_project_id(log)) == "admin"),
        project=sum(
            1 for log in window if audit_service.classify(log.action, audit_service.effective_project_id(log)) == "project"
        ),
        privilege=sum(
            1 for log in window if audit_service.classify(log.action, audit_service.effective_project_id(log)) == "privilege"
        ),
        failed=sum(1 for log in window if audit_service.is_failure(log.action)),
    )

    if category == "failed":
        matching = [log for log in window if audit_service.is_failure(log.action)]
    elif category in audit_service.CATEGORIES:
        matching = [
            log for log in window if audit_service.classify(log.action, audit_service.effective_project_id(log)) == category
        ]
    else:
        matching = window

    items = matching[(page - 1) * page_size : page * page_size]
    actors = await _label_map(User, {log.actor_user_id for log in items if log.actor_user_id}, "email")
    projects = await _label_map(Project, {pid for log in items if (pid := audit_service.effective_project_id(log))}, "name")

    return AuditLogPage(
        items=[_to_response(log, actors, projects) for log in items],
        total=len(matching),
        page=page,
        page_size=page_size,
        counts=counts,
        window_days=days,
    )


_LEVELS_AT_OR_ABOVE = {
    "warning": ["warning", "error", "critical"],
    "error": ["error", "critical"],
    "critical": ["critical"],
}


@router.get("/system", response_model=SystemLogPage)
async def list_system_logs(
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    days: int = Query(1, ge=1, le=90),
    level: str = Query("warning", description="Minimum level: warning | error | critical"),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=500),
):
    """Backend log lines at WARNING and above (see core.log_sink), newest first.

    Unlike the audit trail these are filtered and paged in Mongo: nothing here is derived."""
    since, until = _window(days, since, until)
    levels = _LEVELS_AT_OR_ABOVE.get(level)
    if levels is None:
        raise HTTPException(422, "level must be one of: warning, error, critical")
    query = SystemLog.find(
        SystemLog.created_at >= since, SystemLog.created_at < until, In(SystemLog.level, levels)
    )
    total = await query.count()
    rows = await query.sort(-SystemLog.created_at).skip((page - 1) * page_size).limit(page_size).to_list()
    return SystemLogPage(
        items=[
            SystemLogResponse(
                id=str(r.id),
                level=r.level,
                logger=r.logger,
                message=r.message,
                context=r.context,
                exception=r.exception,
                created_at=as_utc(r.created_at),
            )
            for r in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )

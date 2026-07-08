from fastapi import APIRouter, Depends, Query

from app.core.deps import require_admin
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogResponse
from app.schemas.common import Page

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"], dependencies=[Depends(require_admin)])


def _to_response(log: AuditLog) -> AuditLogResponse:
    return AuditLogResponse(
        id=str(log.id),
        actor_type=log.actor_type,
        actor_user_id=log.actor_user_id,
        action=log.action,
        target_type=log.target_type,
        target_id=log.target_id,
        project_id=log.project_id,
        metadata=log.metadata,
        ip_address=log.ip_address,
        created_at=log.created_at,
    )


@router.get("", response_model=Page)
async def list_audit_logs(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    total = await AuditLog.count()
    logs = (
        await AuditLog.find_all()
        .sort(-AuditLog.created_at)
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )
    return Page(items=[_to_response(log) for log in logs], total=total, page=page, page_size=page_size)

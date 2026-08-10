"""Portal-wide AI usage analytics -- every project's LLM spend in one place, for the admin.

Router-level require_admin (as in admin_scanner_status) because there is no per-handler variation:
nothing here is readable by a non-admin, since it spans projects the caller may not be a member of.
The per-project equivalents live in routers/projects.py behind require_member.
"""

from fastapi import APIRouter, Depends, Query

from app.core.deps import require_admin
from app.schemas.ai_analytics import AiAnalyticsResponse, AiUsageEventPage
from app.services import ai_analytics_service

router = APIRouter(prefix="/admin/ai-analytics", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("", response_model=AiAnalyticsResponse)
async def get_portal_ai_analytics(
    days: int = Query(30, ge=1, le=365),
    project_id: str | None = Query(None, description="Narrow the portal view to one project"),
):
    return await ai_analytics_service.get_analytics(project_id=project_id, days=days)


@router.get("/events", response_model=AiUsageEventPage)
async def list_portal_ai_events(
    days: int = Query(30, ge=1, le=365),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    project_id: str | None = Query(None),
    feature: str | None = Query(None),
    status: str | None = Query(None, pattern="^(success|failed)$"),
):
    return await ai_analytics_service.list_events(
        project_id=project_id, page=page, page_size=page_size, days=days, feature=feature, status=status
    )

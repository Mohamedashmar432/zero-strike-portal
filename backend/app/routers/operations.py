from fastapi import APIRouter, Depends

from app.core.deps import get_current_user, require_admin
from app.models.user import User
from app.schemas.operations import OperationsResponse, QueueResponse
from app.services import operations_service

router = APIRouter(prefix="/admin/operations", tags=["operations"], dependencies=[Depends(require_admin)])
queue_router = APIRouter(prefix="/queue", tags=["operations"])


@router.get("", response_model=OperationsResponse)
async def get_operations() -> OperationsResponse:
    return await operations_service.overview()


@queue_router.get("", response_model=QueueResponse)
async def get_queue(user: User = Depends(get_current_user)) -> QueueResponse:
    """Every queued/running job the caller can see — one request feeds every queued tag on a page."""
    return await operations_service.visible_queue(user)

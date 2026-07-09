from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.core import security
from app.core.deps import get_current_user
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_key import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    ApiKeyValidateRequest,
    ApiKeyValidateResponse,
)
from app.schemas.common import Page
from app.services import audit_service, project_service

router = APIRouter(prefix="/apikeys", tags=["api-keys"])


def _is_active(key: ApiKey) -> bool:
    return key.revoked_at is None and key.expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


def _to_response(key: ApiKey) -> ApiKeyResponse:
    return ApiKeyResponse(
        id=str(key.id),
        project_id=key.project_id,
        label=key.label,
        prefix=key.prefix,
        created_by=key.created_by,
        created_at=key.created_at,
        expires_at=key.expires_at,
        revoked_at=key.revoked_at,
        last_used_at=key.last_used_at,
        last_used_ip=key.last_used_ip,
        is_active=_is_active(key),
    )


@router.post("/validate", response_model=ApiKeyValidateResponse)
async def validate_key(payload: ApiKeyValidateRequest, request: Request):
    key_hash = security.hash_token(payload.token)
    key = await ApiKey.find_one(ApiKey.key_hash == key_hash)
    if not key or not _is_active(key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired API key")

    key.last_used_at = datetime.now(timezone.utc)
    key.last_used_ip = request.client.host if request.client else None
    await key.save()

    return ApiKeyValidateResponse(project_id=key.project_id, key_id=str(key.id), expires_at=key.expires_at)


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: ApiKeyCreateRequest, user: User = Depends(get_current_user)):
    project = await project_service.get_project_or_404(payload.project_id)
    await project_service.require_member(payload.project_id, user)
    if project.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Project is archived")

    raw_token, prefix, key_hash = security.generate_api_key()
    now = datetime.now(timezone.utc)
    key = ApiKey(
        project_id=payload.project_id,
        label=payload.label,
        prefix=prefix,
        key_hash=key_hash,
        created_by=str(user.id),
        created_at=now,
        expires_at=now + timedelta(days=payload.expires_in_days),
    )
    await key.insert()
    await audit_service.record(
        "API Key Created",
        actor_user_id=str(user.id),
        project_id=payload.project_id,
        target_type="api_key",
        target_id=str(key.id),
        metadata={"label": key.label, "prefix": key.prefix, "expires_at": key.expires_at.isoformat()},
    )
    return ApiKeyCreateResponse(
        id=str(key.id),
        project_id=key.project_id,
        label=key.label,
        prefix=key.prefix,
        raw_token=raw_token,
        created_at=key.created_at,
        expires_at=key.expires_at,
    )


@router.get("", response_model=Page)
async def list_api_keys(
    project_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)

    total = await ApiKey.find(ApiKey.project_id == project_id).count()
    keys = (
        await ApiKey.find(ApiKey.project_id == project_id)
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list()
    )
    return Page(items=[_to_response(k) for k in keys], total=total, page=page, page_size=page_size)


@router.get("/{key_id}", response_model=ApiKeyResponse)
async def get_api_key(key_id: str, user: User = Depends(get_current_user)):
    key = await ApiKey.get(key_id)
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    await project_service.require_member(key.project_id, user)
    return _to_response(key)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: str, user: User = Depends(get_current_user)):
    key = await ApiKey.get(key_id)
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    await project_service.require_member(key.project_id, user)

    if key.revoked_at is None:
        key.revoked_at = datetime.now(timezone.utc)
        await key.save()
        await audit_service.record(
            "API Key Revoked",
            actor_user_id=str(user.id),
            project_id=key.project_id,
            target_type="api_key",
            target_id=str(key.id),
            metadata={"label": key.label, "prefix": key.prefix},
        )

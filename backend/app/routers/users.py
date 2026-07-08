from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_current_user, require_admin
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.common import Page
from app.schemas.user import UpdateProfileRequest, UpdateUserRequest

router = APIRouter(tags=["users"])


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=user.is_active
    )


@router.get("/users", response_model=Page, dependencies=[Depends(require_admin)])
async def list_users(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    total = await User.count()
    users = await User.find_all().skip((page - 1) * page_size).limit(page_size).to_list()
    return Page(items=[_to_user_response(u) for u in users], total=total, page=page, page_size=page_size)


@router.get("/users/me", response_model=UserResponse)
async def get_my_profile(user: User = Depends(get_current_user)):
    return _to_user_response(user)


@router.patch("/users/me", response_model=UserResponse)
async def update_my_profile(payload: UpdateProfileRequest, user: User = Depends(get_current_user)):
    if payload.name is not None:
        user.name = payload.name
        user.updated_at = datetime.now(timezone.utc)
        await user.save()
    return _to_user_response(user)


@router.get("/users/{user_id}", response_model=UserResponse, dependencies=[Depends(require_admin)])
async def get_user(user_id: str):
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return _to_user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse, dependencies=[Depends(require_admin)])
async def update_user(user_id: str, payload: UpdateUserRequest):
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    return _to_user_response(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_user(user_id: str):
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    await user.delete()

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_current_user, require_admin
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.common import Page
from app.schemas.user import ChangePasswordRequest, UpdateProfileRequest, UpdateUserRequest
from app.services import audit_service, auth_service

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
    changed = False
    if payload.name is not None:
        user.name = payload.name
        changed = True
    if payload.email is not None and payload.email != user.email:
        existing = await User.find_one(User.email == payload.email)
        if existing and str(existing.id) != str(user.id):
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use")
        user.email = payload.email
        changed = True
    if changed:
        user.updated_at = datetime.now(timezone.utc)
        await user.save()
    return _to_user_response(user)


@router.post("/users/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(payload: ChangePasswordRequest, user: User = Depends(get_current_user)):
    await auth_service.change_password(user, payload.current_password, payload.new_password)
    await audit_service.record("password_changed", actor_user_id=str(user.id))


@router.get("/users/{user_id}", response_model=UserResponse, dependencies=[Depends(require_admin)])
async def get_user(user_id: str):
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return _to_user_response(user)


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, payload: UpdateUserRequest, admin: User = Depends(require_admin)):
    if user_id == str(admin.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot modify your own account through this endpoint")
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    user.updated_at = datetime.now(timezone.utc)
    await user.save()
    await audit_service.record(
        "User Updated",
        actor_user_id=str(admin.id),
        target_type="user",
        target_id=str(user.id),
        metadata={"role": user.role, "is_active": user.is_active},
    )
    return _to_user_response(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, admin: User = Depends(require_admin)):
    if user_id == str(admin.id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot modify your own account through this endpoint")
    user = await User.get(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    await user.delete()
    await audit_service.record(
        "User Deleted",
        actor_user_id=str(admin.id),
        target_type="user",
        target_id=user_id,
        metadata={"email": user.email},
    )

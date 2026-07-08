from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response, status

from app.core.deps import get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPairResponse,
    UserResponse,
)
from app.services import audit_service, auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _to_user_response(user: User) -> UserResponse:
    return UserResponse(
        id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=user.is_active
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest):
    user = await auth_service.register(payload.email, payload.password, payload.name)
    await audit_service.record("register", actor_user_id=str(user.id))
    return _to_user_response(user)


@router.post("/login", response_model=TokenPairResponse)
async def login(payload: LoginRequest, request: Request):
    user = await auth_service.authenticate(payload.email, payload.password)
    access_token, refresh_token, expires_in = await auth_service.issue_token_pair(
        user, user_agent=request.headers.get("user-agent"), ip=request.client.host if request.client else None
    )
    user.last_login_at = datetime.now(timezone.utc)
    await user.save()
    await audit_service.record(
        "login", actor_user_id=str(user.id), ip_address=request.client.host if request.client else None
    )
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)


@router.post("/refresh", response_model=TokenPairResponse)
async def refresh(payload: RefreshRequest, request: Request):
    access_token, refresh_token, expires_in = await auth_service.refresh_token_pair(
        payload.refresh_token,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    return TokenPairResponse(access_token=access_token, refresh_token=refresh_token, expires_in=expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: LogoutRequest):
    user_id = await auth_service.logout(payload.refresh_token)
    if user_id:
        await audit_service.record("logout", actor_user_id=user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return _to_user_response(user)

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core import security
from app.models.user import User
from app.services import api_key_service

_bearer = HTTPBearer()
_api_key_bearer = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> User:
    try:
        claims = security.decode_token(credentials.credentials)
    except security.JWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if claims.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token type")
    user = await User.get(claims["sub"])
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin privileges required")
    return user


@dataclass
class ApiKeyContext:
    project_id: str
    key_id: str


async def get_api_key_context(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_api_key_bearer),
) -> ApiKeyContext:
    """Scanner-facing auth: the Bearer credential is an opaque API key (not a JWT).

    Resolves it to the project it scopes. Yields an ApiKeyContext, never a User —
    so scanner handlers and JWT handlers can never receive each other's principal.
    """
    key = await api_key_service.resolve_api_key(credentials.credentials, request)
    return ApiKeyContext(project_id=key.project_id, key_id=str(key.id))

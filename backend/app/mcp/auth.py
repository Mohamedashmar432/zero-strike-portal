"""ASGI auth wrapper for the mounted MCP app — a third principal type beside the JWT user and
the scanner API key (docs/ADMIN_MCP.md). Never shared with a FastAPI dependency."""

from contextvars import ContextVar
from dataclasses import dataclass

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.rate_limit import client_ip
from app.services import mcp_token_service


@dataclass(frozen=True)
class McpPrincipal:
    user_id: str
    email: str
    token_id: str


current_principal: ContextVar[McpPrincipal | None] = ContextVar("mcp_principal", default=None)


class McpAuthMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        scheme, _, raw = request.headers.get("authorization", "").partition(" ")
        resolved = (
            await mcp_token_service.resolve(raw.strip(), client_ip(request))
            if scheme.lower() == "bearer" and raw.strip()
            else None
        )
        if resolved is None:
            await self._refuse(scope, receive, send, 401, "Invalid or expired MCP token")
            return
        token, user = resolved
        # Re-checked on every request: demoting or disabling the admin ends their MCP access
        # immediately, with no token to remember to revoke.
        if not user.is_active or user.approval_status != "approved" or user.role != "admin":
            await self._refuse(scope, receive, send, 403, "Admin privileges required")
            return
        reset = current_principal.set(McpPrincipal(str(user.id), user.email, str(token.id)))
        try:
            await self.app(scope, receive, send)
        finally:
            current_principal.reset(reset)

    @staticmethod
    async def _refuse(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
        headers = {"WWW-Authenticate": "Bearer"} if status == 401 else None
        await JSONResponse({"detail": detail}, status_code=status, headers=headers)(scope, receive, send)

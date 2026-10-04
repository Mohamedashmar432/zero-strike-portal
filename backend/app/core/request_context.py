"""Per-request client context (IP, user agent) for audit rows written deep in services.

Bound by a FastAPI dependency, not BaseHTTPMiddleware: middleware runs the endpoint in a
different task, so a ContextVar set there would not be visible to the handler's task. The
owning task is stored alongside the values, so a task spawned from a handler (a background
scan, an email fan-out) does not inherit a request's IP when it copies the context.
"""

import asyncio
from contextvars import ContextVar

from fastapi import Request

from app.core.rate_limit import client_ip

_ctx: ContextVar[tuple[asyncio.Task | None, str | None, str | None] | None] = ContextVar(
    "request_context", default=None
)


async def bind_request_context(request: Request) -> None:
    _ctx.set((asyncio.current_task(), client_ip(request), request.headers.get("user-agent")))


def current() -> tuple[str | None, str | None]:
    """(ip, user_agent) of the request owning the running task, else (None, None)."""
    stored = _ctx.get()
    if stored is None:
        return None, None
    task, ip, user_agent = stored
    if task is not asyncio.current_task():
        return None, None
    return ip, user_agent

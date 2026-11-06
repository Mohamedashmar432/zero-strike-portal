import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


# An API serves JSON, never a page to frame or script: nothing here needs to be embeddable.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Defensive response headers on every API response. setdefault: a route that sets its own wins."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for name, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Binds a request ID to structlog's contextvars for the life of the request, so every
    log line emitted while handling it (across routers/services) carries the same id —
    and echoes it back as a response header so a client-reported issue can be traced to
    its exact log lines. Reuses an inbound `X-Request-ID` if the proxy in front already set one.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

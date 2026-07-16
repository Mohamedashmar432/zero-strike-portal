import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


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

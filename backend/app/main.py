import asyncio
import contextlib
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.middleware import RequestIDMiddleware
from app.db.mongo import close_mongo_connection, connect_to_mongo, get_database
from app.routers import (
    admin_downloads,
    admin_scanner_status,
    ai_analysis,
    ai_provider_config,
    api_keys,
    audit_logs,
    auth,
    connections,
    dashboard,
    downloads,
    projects,
    public_repos,
    repo_credentials,
    report_templates,
    scanner_scans,
    scans,
    users,
)
from app.services import (
    ai_job_queue_service,
    cloud_scan_service,
    project_stats_service,
    scan_queue_service,
)
from app.services.oauth import OAuthProviderError

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await connect_to_mongo()
    if not cloud_scan_service.scanner_available():
        # Loud and immediate on boot, rather than a surprise buried in the first cloud scan's
        # error_message — every cloud scan will fail until SCANNER_BINARY_PATH is fixed and the
        # backend is restarted (this setting is only read at process startup).
        logger.warning(
            "Scanner binary %r not found (SCANNER_BINARY_PATH) — cloud scans will fail until this "
            "is fixed and the backend is restarted.",
            settings.scanner_binary_path,
        )
    # Backfill/reconcile the denormalized per-project findings counters (no-op after first boot).
    # Non-fatal: stats degrade to stale counters if it fails, the app still boots.
    try:
        await project_stats_service.reconcile_project_finding_counts()
    except Exception:
        logger.warning("Project findings-counter reconciliation failed on startup", exc_info=True)
    poll_task = asyncio.create_task(scan_queue_service.poll_loop())
    ai_poll_task = asyncio.create_task(ai_job_queue_service.poll_loop())
    yield
    poll_task.cancel()
    ai_poll_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await poll_task
    with contextlib.suppress(asyncio.CancelledError):
        await ai_poll_task
    await close_mongo_connection()


def create_app() -> FastAPI:
    app = FastAPI(title="ZeroStrike Portal API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added after CORS so it's the outermost layer (Starlette wraps in reverse add order) —
    # every request gets a request_id bound before anything else runs.
    app.add_middleware(RequestIDMiddleware)

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(audit_logs.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(dashboard.router, prefix="/api/v1")
    app.include_router(api_keys.router, prefix="/api/v1")
    app.include_router(scans.router, prefix="/api/v1")
    app.include_router(scanner_scans.router, prefix="/api/v1")
    app.include_router(connections.router, prefix="/api/v1")
    app.include_router(repo_credentials.router, prefix="/api/v1")
    app.include_router(public_repos.router, prefix="/api/v1")
    app.include_router(downloads.router, prefix="/api/v1")
    app.include_router(admin_downloads.router, prefix="/api/v1")
    app.include_router(admin_scanner_status.router, prefix="/api/v1")
    app.include_router(report_templates.router, prefix="/api/v1")
    app.include_router(ai_analysis.router, prefix="/api/v1")
    app.include_router(ai_analysis.finding_scan_router, prefix="/api/v1")
    app.include_router(ai_provider_config.router, prefix="/api/v1")

    @app.exception_handler(OAuthProviderError)
    async def oauth_provider_error_handler(request: Request, exc: OAuthProviderError):
        # A GitHub/Azure DevOps API call failed (bad/expired token, rate limit, outage) — 502 signals
        # our server is fine but the upstream provider isn't, distinct from a validation 4xx.
        return JSONResponse(status_code=502, content={"detail": str(exc)})

    @app.get("/health")
    async def health():
        mongo_ok = True
        try:
            await get_database().command("ping")
        except Exception:
            mongo_ok = False
        scanner_ok = cloud_scan_service.scanner_available()
        healthy = mongo_ok and scanner_ok
        body = {"status": "ok" if healthy else "degraded", "mongo": mongo_ok, "scanner": scanner_ok}
        return JSONResponse(status_code=200 if healthy else 503, content=body)

    return app


app = create_app()

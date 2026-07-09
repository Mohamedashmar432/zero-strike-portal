from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logging import configure_logging
from app.db.mongo import close_mongo_connection, connect_to_mongo
from app.routers import api_keys, audit_logs, auth, projects, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    await connect_to_mongo()
    yield
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

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(audit_logs.router, prefix="/api/v1")
    app.include_router(projects.router, prefix="/api/v1")
    app.include_router(api_keys.router, prefix="/api/v1")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()

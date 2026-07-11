import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient, enabled_gridfs_integration

import app.core.rate_limit as rate_limit_module
import app.db.mongo as mongo_module
from app.core.rate_limit import RateLimiter

mongo_module.AsyncIOMotorClient = AsyncMongoMockClient

from app.main import create_app  # noqa: E402


@pytest.fixture()
def client():
    # rate_limit.limiter is a module-level singleton shared across the whole test process —
    # without resetting it, hit counts leak between tests (e.g. every test that registers a
    # user shares the same TestClient IP, so the IP-only register rate limit would eventually
    # 429 unrelated tests). Give every test a fresh limiter.
    rate_limit_module.limiter = RateLimiter()
    # enabled_gridfs_integration() lets Motor's GridFS bucket (used by download_service)
    # accept the mocked Database/Collection types — only needed for tests.
    with enabled_gridfs_integration(), TestClient(create_app()) as c:
        yield c

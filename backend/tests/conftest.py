# ruff: noqa: E402
import os

# Tests must never reach a real mail relay or Key Vault, whatever the developer's local .env
# says. Real env vars outrank .env in pydantic-settings, so blank them before the app imports.
# Tests that exercise email set `settings.smtp_host` themselves via monkeypatch.
for _name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "AZURE_KEY_VAULT_URL"):
    os.environ[_name] = ""
# mongomock resolves an mongodb+srv:// URI over real DNS (slow/flaky offline), so give it a plain one.
os.environ["MONGODB_URI"] = "mongodb://localhost:27017"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
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

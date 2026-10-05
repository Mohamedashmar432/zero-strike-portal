# ruff: noqa: E402
import os

# Tests must never reach a real mail relay or Key Vault, whatever the developer's local .env
# says. Real env vars outrank .env in pydantic-settings, so blank them before the app imports.
# Tests that exercise email set `settings.smtp_host` themselves via monkeypatch.
for _name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "AZURE_KEY_VAULT_URL"):
    os.environ[_name] = ""
# mongomock resolves an mongodb+srv:// URI over real DNS (slow/flaky offline), so give it a plain one.
os.environ["MONGODB_URI"] = "mongodb://localhost:27017"
# The app's startup sweep and every clone/remediation workdir land here, never in the developer's
# real %TEMP%/zs-clones (which the sweep would otherwise prune).
import tempfile  # noqa: E402

os.environ["CLONE_WORKDIR_PATH"] = tempfile.mkdtemp(prefix="zs-test-clones-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient, enabled_gridfs_integration

import app.core.rate_limit as rate_limit_module
import app.db.mongo as mongo_module
from app.core.rate_limit import RateLimiter

mongo_module.AsyncIOMotorClient = AsyncMongoMockClient

from app.main import create_app  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_llm_calls(monkeypatch):
    """Tests never reach a real LLM provider. Without this, any code path a test leaves unstubbed
    (e.g. the remediation critic behind a stubbed agent) sent a real HTTPS request to the provider
    with the fake key "k" -- so the test's timing, and its outcome, depended on that provider's
    latency and availability: a 429/5xx/reset is a transient error, retried with a 5 s backoff,
    which blew past the auto-fix poll budget and failed
    test_repeated_runs_advance_through_a_scan_larger_than_one_batch intermittently.

    The stub fails the way the real endpoint does for a bogus key (an authentication error, which
    llm_client treats as permanent), so every caller degrades exactly as before -- instantly and
    deterministically. A test that wants a response patches `litellm.acompletion` itself; its
    monkeypatch runs after this one and wins."""
    import litellm

    async def _offline_acompletion(**kwargs):
        raise litellm.AuthenticationError(
            message="tests run offline: no real LLM provider is reachable",
            llm_provider=str(kwargs.get("custom_llm_provider") or "test"),
            model=str(kwargs.get("model") or "test"),
        )

    monkeypatch.setattr(litellm, "acompletion", _offline_acompletion)


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

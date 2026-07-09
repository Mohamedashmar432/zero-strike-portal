import os
import tempfile

# Point artifact storage at a throwaway dir before Settings is instantiated, so
# tests never write scan artifacts into the repo's ./data/artifacts.
os.environ.setdefault("ARTIFACT_STORAGE_PATH", tempfile.mkdtemp(prefix="zs-test-artifacts-"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from mongomock_motor import AsyncMongoMockClient  # noqa: E402

import app.db.mongo as mongo_module  # noqa: E402

mongo_module.AsyncIOMotorClient = AsyncMongoMockClient

from app.main import create_app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(create_app()) as c:
        yield c

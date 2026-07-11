import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient, enabled_gridfs_integration

import app.db.mongo as mongo_module

mongo_module.AsyncIOMotorClient = AsyncMongoMockClient

from app.main import create_app  # noqa: E402


@pytest.fixture()
def client():
    # enabled_gridfs_integration() lets Motor's GridFS bucket (used by download_service)
    # accept the mocked Database/Collection types — only needed for tests.
    with enabled_gridfs_integration(), TestClient(create_app()) as c:
        yield c

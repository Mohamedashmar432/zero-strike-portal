from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.finding import Finding
from app.models.oauth_connection import OAuthConnection
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.report import Report
from app.models.scan import Scan
from app.models.scanner_binary import ScannerBinary
from app.models.user import User

_client: AsyncIOMotorClient | None = None


def get_database():
    """The active Motor database — for raw access (e.g. GridFS) outside Beanie's ODM layer."""
    assert _client is not None, "connect_to_mongo() has not run yet"
    return _client[settings.mongodb_db_name]


async def connect_to_mongo() -> None:
    global _client
    _client = AsyncIOMotorClient(settings.mongodb_uri)
    await init_beanie(
        database=_client[settings.mongodb_db_name],
        document_models=[
            User,
            Project,
            ProjectMember,
            ApiKey,
            Scan,
            Finding,
            Report,
            AuditLog,
            ScannerBinary,
            OAuthConnection,
        ],
    )


async def close_mongo_connection() -> None:
    if _client is not None:
        _client.close()

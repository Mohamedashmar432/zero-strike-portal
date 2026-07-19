from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import settings
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.ai_finding_insight import AIFindingInsight
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_provider_config import AIProviderConfig
from app.models.ai_scan_insight import AIScanInsight
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.finding import Finding
from app.models.oauth_connection import OAuthConnection
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_repo import ProjectRepo
from app.models.report import Report
from app.models.repo_credential import RepoCredential
from app.models.scan import Scan
from app.models.scanner_binary import ScannerBinary
from app.models.user import User
from app.models.workspace_settings import WorkspaceSettings

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
            RepoCredential,
            ProjectRepo,
            WorkspaceSettings,
            AIFindingInsight,
            AIScanInsight,
            AIFixProposal,
            AIProviderConfig,
            AIAnalysisJob,
        ],
    )


async def close_mongo_connection() -> None:
    if _client is not None:
        _client.close()

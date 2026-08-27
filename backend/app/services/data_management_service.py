"""The single registry of what portal data is disposable, and the one place it gets deleted.

Two callers share it so they can never drift apart:
  * the admin "Data Management" purge (routers/admin_data.py) — clearing test/demo data;
  * project_service.delete_project_cascade — deleting one project.

Anything NOT listed here is deliberately never purged: User, WorkspaceSettings,
AIProviderConfig / RepoCredential / OAuthConnection (credentials), RemediationSettings
(a workspace singleton) and ScannerBinary (GridFS build artifacts, not portal data).
Adding a project-scoped collection? Add it here — the cascade picks it up for free.
"""

from dataclasses import dataclass, field

from beanie import Document
from bson import ObjectId
from bson.errors import InvalidId

from app.models.ai_analysis_job import AIAnalysisJob
from app.models.ai_finding_insight import AIFindingInsight
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.ai_scan_insight import AIScanInsight
from app.models.ai_usage_event import AIUsageEvent
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.compliance_audit import ComplianceAudit
from app.models.finding import Finding
from app.models.finding_comment import FindingComment
from app.models.fix_conversation import FixConversation
from app.models.fix_pattern import FixPattern
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.models.project_repo import ProjectRepo
from app.models.remediation_project_doc import RemediationProjectDoc
from app.models.report import Report
from app.models.scan import Scan


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    description: str
    models: tuple[type[Document], ...]
    # Purging these categories is meaningless without also purging the ones they imply —
    # e.g. deleting projects while keeping their scans just orphans the scans.
    implies: tuple[str, ...] = field(default=())
    destructive: bool = False


CATEGORIES: tuple[Category, ...] = (
    Category(
        key="scan_data",
        label="Scans, findings & reports",
        description="Every scan and everything derived from it. Projects, keys and users are kept.",
        models=(Scan, Finding, Report, FindingComment),
        implies=("ai_artifacts", "compliance"),
    ),
    Category(
        key="ai_artifacts",
        label="AI insights & fix proposals",
        description="Cached AI explanations, auto-fix proposals, remediation jobs and learned patterns.",
        models=(
            AIScanInsight,
            AIFindingInsight,
            AIFixProposal,
            AIAnalysisJob,
            RemediationJob,
            FixConversation,
            RemediationProjectDoc,
            FixPattern,
        ),
    ),
    Category(
        key="compliance",
        label="Compliance audits",
        description="Generated compliance audit runs and their framework results.",
        models=(ComplianceAudit,),
    ),
    Category(
        key="ai_usage",
        label="AI usage log",
        description="Per-call LLM usage events behind the AI analytics dashboards.",
        models=(AIUsageEvent,),
    ),
    Category(
        key="audit_log",
        label="Audit log",
        description="Portal activity trail. The purge itself is recorded after the wipe.",
        models=(AuditLog,),
    ),
    Category(
        key="projects",
        label="Projects",
        description="Projects with their members, API keys and connected repositories.",
        models=(Project, ProjectMember, ApiKey, ProjectRepo),
        implies=("scan_data", "ai_artifacts", "compliance", "ai_usage"),
        destructive=True,
    ),
)

_BY_KEY = {c.key: c for c in CATEGORIES}


def expand(keys: list[str]) -> list[str]:
    """Close the requested keys over `implies`, preserving CATEGORIES order."""
    wanted: set[str] = set()
    pending = list(keys)
    while pending:
        key = pending.pop()
        if key in wanted or key not in _BY_KEY:
            continue
        wanted.add(key)
        pending.extend(_BY_KEY[key].implies)
    return [c.key for c in CATEGORIES if c.key in wanted]


def _scope(model: type[Document], project_id: str | None) -> dict:
    """Mongo filter restricting a model to one project (Project itself matches on _id)."""
    if project_id is None:
        return {}
    if model is Project:
        try:
            return {"_id": ObjectId(project_id)}
        except InvalidId:
            return {"_id": None}  # matches nothing rather than raising
    return {"project_id": project_id}


async def get_stats(project_id: str | None = None) -> list[dict]:
    """Per-category document counts, broken down by collection so the UI can show what dies."""
    out = []
    for category in CATEGORIES:
        collections = [
            {
                "name": model.get_collection_name(),
                "count": await model.find(_scope(model, project_id)).count(),
            }
            for model in category.models
        ]
        out.append(
            {
                "key": category.key,
                "label": category.label,
                "description": category.description,
                "destructive": category.destructive,
                "implies": list(category.implies),
                "total": sum(c["count"] for c in collections),
                "collections": collections,
            }
        )
    return out


async def purge(categories: list[str], project_id: str | None = None) -> dict[str, int]:
    """Delete every collection in the (implication-expanded) categories. Returns rows deleted
    per collection. Counting before deleting costs an extra query — irrelevant for a one-shot
    admin action, and mongomock's DeleteResult is not reliable enough to trust instead.
    """
    deleted: dict[str, int] = {}
    for key in expand(categories):
        for model in _BY_KEY[key].models:
            scope = _scope(model, project_id)
            name = model.get_collection_name()
            count = await model.find(scope).count()
            if count:
                await model.find(scope).delete()
            deleted[name] = deleted.get(name, 0) + count
    return deleted


async def purge_project(project_id: str) -> dict[str, int]:
    """Everything belonging to one project, the project document included."""
    return await purge(["projects"], project_id=project_id)

"""The dependency inventory the Go scanner reports with each scan (docs/LIVE_DEPENDENCY_ALERTS.md).

One snapshot per (project, repo scope), replaced on every ingest that carries a `Dependencies` array.
It exists so a package that is clean today can be matched against an advisory published tomorrow --
Finding.dependency only ever holds packages that were already vulnerable. `direct` is stored as the
scanner reported it, raw: that flag is unreliable and must not be shown to users."""

from datetime import datetime, timezone

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel

MAX_DEPS = 20_000
MAX_MANIFESTS = 10


class InventoryDep(BaseModel):
    k: str  # "<ecosystem>|<normalised package name>" -- core.advisory.dep_key
    ecosystem: str
    package: str  # as the manifest spells it (the scanner fingerprints this form)
    version: str
    manifests: list[str] = Field(default_factory=list)
    direct: bool | None = None


class DependencyInventory(Document):
    project_id: str
    repo_scope_key: str  # project_stats_service.repo_key_resolver grouping, like Vulnerability
    project_repo_id: str | None = None
    repo_label: str = ""
    scan_id: str
    scan_type: str = "cloud"
    git_commit: str | None = None
    branch: str | None = None
    scanner_version: str | None = None
    scanned_at: datetime
    dep_count: int = 0
    truncated: bool = False
    deps: list[InventoryDep] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "dependency_inventories"
        indexes = [
            IndexModel([("project_id", 1), ("repo_scope_key", 1)], unique=True),
            IndexModel([("deps.k", 1)]),
            IndexModel([("project_id", 1)]),
        ]

from datetime import datetime
from typing import Literal

from beanie import Document
from pymongo import IndexModel


class Scan(Document):
    project_id: str
    api_key_id: str | None = None
    scan_type: Literal["local", "cloud", "cicd"]
    triggered_by: Literal["cli", "ci", "cloud", "manual"] = "cli"
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    scanner_version: str | None = None
    hostname: str | None = None
    git_commit: str | None = None
    branch: str | None = None
    scan_label: str | None = None
    repo_url: str | None = None
    ci_provider: Literal["github_actions", "gitlab_ci", "azure_pipelines"] | None = None
    created_by: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "scans"
        indexes = [
            IndexModel([("project_id", 1), ("started_at", -1)]),
            IndexModel([("status", 1)]),
            IndexModel([("project_id", 1), ("created_at", -1)]),
            IndexModel([("project_id", 1), ("scan_type", 1)]),
        ]

from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from pymongo import IndexModel


class ProjectRepo(Document):
    """One repo connected to a project for cloud scans. A project may hold several of these (multiple
    repos per project). Stores its own copy of the encrypted PAT at connect time rather than a live
    reference to a RepoCredential — editing/removing a saved credential in Settings, or connecting a
    different project to a different account, can never change or break an already-connected repo.

    pat_encrypted is None for a public GitHub repo connected with no credential at all (see
    project_repo_service.add_repo) — the clone runs anonymously."""

    project_id: Indexed(str)  # type: ignore[valid-type]
    provider: Literal["github", "azure_devops"]
    organization: str
    ado_project: str | None = None
    repo_full_name: str
    clone_url: str
    selected_branch: str
    label: str | None = None
    pat_encrypted: str | None = None
    source_credential_id: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "project_repos"
        indexes = [IndexModel([("project_id", 1)])]

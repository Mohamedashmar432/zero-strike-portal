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
    # Repo Sync (docs/REPO_SYNC.md): the remote branch head seen at the last check, and the
    # lease that stops two overlapping syncs from both enqueueing a scan. The scanned commit
    # itself lives on the latest completed Scan, never here.
    remote_head_sha: str | None = None
    remote_head_checked_at: datetime | None = None
    last_sync_error: str | None = None
    sync_lease_until: datetime | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "project_repos"
        indexes = [IndexModel([("project_id", 1)])]

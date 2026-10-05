from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.repo_url import check_repo_url_syntax


class ProjectRepoCreateRequest(BaseModel):
    # Either reference a saved Settings credential...
    credential_id: str | None = None
    # ...or supply a one-off PAT inline, not saved to Settings...
    provider: Literal["github", "azure_devops"] | None = None
    pat: str | None = None
    organization: str | None = None
    ado_project: str | None = None
    # ...or, for an open-source GitHub repo, skip credentials entirely — the server verifies the
    # repo is actually public (see project_repo_service.add_repo) before connecting it with no
    # stored token at all.
    public: bool = False
    # The repo + branch already picked client-side via the repos/branches listing endpoints.
    repo_full_name: str
    clone_url: str
    selected_branch: str
    label: str | None = None

    @field_validator("clone_url")
    @classmethod
    def _validate_clone_url(cls, v: str) -> str:
        check_repo_url_syntax(v)
        return v

    @model_validator(mode="after")
    def _validate_credential_source(self):
        if self.public:
            if self.provider != "github":
                raise ValueError("Credential-free connections are only supported for public GitHub repos")
            return self
        if self.credential_id:
            return self
        if self.provider and self.pat:
            # organization is only meaningful to Azure DevOps (it's the dev.azure.com/{org} segment).
            # For GitHub it's a display label the API never reads, so it's derived from the repo
            # owner rather than asked for — see project_repo_service.add_repo.
            if self.provider == "github" or self.organization:
                return self
            raise ValueError("organization is required for Azure DevOps")
        raise ValueError("Provide credential_id, provider+pat, or public=true (GitHub only)")


class ProjectRepoUpdateRequest(BaseModel):
    selected_branch: str


class ProjectRepoReauthRequest(BaseModel):
    pat: str


class ProjectRepoResponse(BaseModel):
    id: str
    project_id: str
    provider: Literal["github", "azure_devops"]
    organization: str
    ado_project: str | None
    repo_full_name: str
    clone_url: str
    selected_branch: str
    label: str | None
    created_at: datetime
    # Repo Sync state (docs/REPO_SYNC.md), derived on read in repo_sync_service.sync_overviews.
    remote_head_sha: str | None = None
    scanned_commit: str | None = None
    scanned_branch: str | None = None
    last_synced_at: datetime | None = None
    active_scan_id: str | None = None
    last_sync_error: str | None = None
    sync_state: Literal["syncing", "up_to_date", "behind", "error", "never", "unknown"] = "unknown"
    #: Auto-fix PRs (distinct PRs, not proposals) still open on the provider as last read, and those
    #: merged after `last_synced_at` -- the "N auto-fix PRs merged since last sync" reminder.
    autofix_open_prs: int = 0
    autofix_merged_since_sync: int = 0


class RepoSyncRequest(BaseModel):
    # Bypass the "already scanned this commit" short circuit ("Rescan anyway").
    force: bool = False


class RepoSyncResponse(BaseModel):
    outcome: Literal["up_to_date", "scan_queued", "already_syncing"]
    scan_id: str | None
    remote_head_sha: str | None
    repo: ProjectRepoResponse


class PrStatusRefreshResponse(BaseModel):
    """POST /projects/{id}/repos/{repo_id}/pr-status/refresh. `errors` are sanitized provider
    messages; a failure for one PR never stops the others or the response."""

    checked: int
    open: int
    merged: int
    closed: int
    newly_merged: int
    errors: list[str] = Field(default_factory=list)
    repo: ProjectRepoResponse

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator


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

    @model_validator(mode="after")
    def _validate_credential_source(self):
        if self.public:
            if self.provider != "github":
                raise ValueError("Credential-free connections are only supported for public GitHub repos")
            return self
        if self.credential_id:
            return self
        if self.provider and self.pat and self.organization:
            return self
        raise ValueError("Provide credential_id, provider+pat+organization, or public=true (GitHub only)")


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

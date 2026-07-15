from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator


class ProjectRepoCreateRequest(BaseModel):
    # Either reference a saved Settings credential...
    credential_id: str | None = None
    # ...or supply a one-off PAT inline, not saved to Settings.
    provider: Literal["github", "azure_devops"] | None = None
    pat: str | None = None
    organization: str | None = None
    ado_project: str | None = None
    # The repo + branch already picked client-side via the repos/branches listing endpoints.
    repo_full_name: str
    clone_url: str
    selected_branch: str
    label: str | None = None

    @model_validator(mode="after")
    def _validate_credential_source(self):
        if self.credential_id:
            return self
        if self.provider and self.pat and self.organization:
            return self
        raise ValueError("Provide either credential_id or provider+pat+organization")


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

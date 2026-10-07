from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RepoCredentialCreateRequest(BaseModel):
    provider: Literal["github", "azure_devops"]
    pat: str
    organization: str
    # Optional: an Azure DevOps credential is org-wide and the project is picked per connection.
    # Older credentials saved with one still work — it becomes their default project.
    ado_project: str | None = None
    label: str | None = None


class RepoCredentialResponse(BaseModel):
    id: str
    provider: Literal["github", "azure_devops"]
    organization: str
    ado_project: str | None
    label: str | None
    created_at: datetime


class RepoResponse(BaseModel):
    id: str
    name: str
    full_name: str
    clone_url: str
    private: bool
    default_branch: str | None


class AdoProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None = None


class BranchResponse(BaseModel):
    name: str


class RepoLookupRequest(BaseModel):
    # "owner/repo" — the frontend strips a pasted https://github.com/... URL down to this.
    repo_full_name: str
    pat: str


class RepoLookupResponse(BaseModel):
    repo: RepoResponse
    branches: list[BranchResponse]

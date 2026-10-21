from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class RepoCredentialUpdateRequest(BaseModel):
    """Only the fields the caller sends change (`model_fields_set`), so `ado_project: null` clears the
    default project while omitting it leaves it alone. Changing organization/project re-checks the
    stored token against the new target before saving."""

    label: str | None = Field(default=None, max_length=80)
    organization: str | None = Field(default=None, min_length=1, max_length=200)
    ado_project: str | None = Field(default=None, max_length=200)


class RepoCredentialReconnectRequest(BaseModel):
    pat: str = Field(min_length=1)


class RepoCredentialStatusResponse(BaseModel):
    """`connected` = the stored token still lists repos/projects; `invalid` = it no longer does
    (revoked, expired, wrong scope, or unreadable) and the user should reconnect."""

    status: Literal["connected", "invalid"]
    detail: str | None = None
    checked_at: datetime


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

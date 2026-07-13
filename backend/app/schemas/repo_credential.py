from datetime import datetime
from typing import Literal

from pydantic import BaseModel, model_validator


class RepoCredentialCreateRequest(BaseModel):
    provider: Literal["github", "azure_devops"]
    pat: str
    organization: str
    ado_project: str | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _validate_ado_project(self):
        if self.provider == "azure_devops" and not self.ado_project:
            raise ValueError("ado_project is required for Azure DevOps")
        return self


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


class BranchResponse(BaseModel):
    name: str

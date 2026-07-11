from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ConnectionResponse(BaseModel):
    id: str
    provider: Literal["github", "azure_devops"]
    account_login: str
    connected_at: datetime


class AuthorizeResponse(BaseModel):
    authorize_url: str


class RepoResponse(BaseModel):
    id: str
    name: str
    full_name: str
    clone_url: str
    private: bool
    default_branch: str | None


class OrgResponse(BaseModel):
    id: str
    name: str


class AzureProjectResponse(BaseModel):
    id: str
    name: str

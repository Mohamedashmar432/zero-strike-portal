from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from pymongo import IndexModel


class RepoCredential(Document):
    """A user's saved GitHub/Azure DevOps Personal Access Token, for connecting repos to projects
    (see ProjectRepo) — distinct from the dormant OAuthConnection flow and from per-project scanner
    ApiKeys. A user may save several of these per provider (different orgs/accounts): saving one here
    does not bind it to any project by itself, and it is never treated as a single "current" shared
    credential — ProjectRepo copies the encrypted PAT onto its own row at connect time, so removing or
    editing a credential here can't break or cross-contaminate an already-connected project."""

    user_id: Indexed(str)  # type: ignore[valid-type]
    provider: Literal["github", "azure_devops"]
    organization: str
    ado_project: str | None = None
    label: str | None = None
    pat_encrypted: str
    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "repo_credentials"
        indexes = [IndexModel([("user_id", 1), ("provider", 1)])]

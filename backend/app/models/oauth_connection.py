from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from pymongo import IndexModel


class OAuthConnection(Document):
    """A user's linked GitHub/Azure DevOps identity, used to import repos into a cloud scan without
    hand-pasting a repo URL + PAT. Per-user, not per-project — an OAuth identity is a personal
    credential, so any project the user is a member of can use it at scan-creation time (see
    connection_service.get_decrypted_token)."""

    user_id: Indexed(str)  # type: ignore[valid-type]
    provider: Literal["github", "azure_devops"]
    account_login: str
    external_account_id: str
    access_token_encrypted: str
    refresh_token_encrypted: str | None = None
    token_expires_at: datetime | None = None  # null for GitHub (never expires); set for Azure DevOps
    scope: str | None = None
    connected_at: datetime
    updated_at: datetime

    class Settings:
        name = "oauth_connections"
        indexes = [IndexModel([("user_id", 1), ("provider", 1)], unique=True)]

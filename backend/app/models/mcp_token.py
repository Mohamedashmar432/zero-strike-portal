from datetime import datetime

from beanie import Document, Indexed
from pymongo import IndexModel


class McpToken(Document):
    """A personal admin credential for the MCP server (docs/ADMIN_MCP.md). Resolves to a User,
    whose admin role is re-checked on every request — the token itself carries no authority."""

    user_id: Indexed(str)  # type: ignore[valid-type]
    label: str
    prefix: str
    key_hash: Indexed(str, unique=True)  # type: ignore[valid-type]
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    last_used_ip: str | None = None

    class Settings:
        name = "mcp_tokens"
        indexes = [IndexModel([("user_id", 1), ("revoked_at", 1)])]

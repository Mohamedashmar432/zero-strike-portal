from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from pymongo import IndexModel

# Every key today is functionally a "scanner" key (the CLI/CI client). "ai_agent" is
# reserved for a future automated principal (AI analysis/auto-fix) that should be
# distinguishable from — and eventually more limited than — a human-issued scanner key.
ApiKeyScope = Literal["scanner", "ai_agent"]


class ApiKey(Document):
    project_id: Indexed(str)  # type: ignore[valid-type]
    label: str
    prefix: str
    key_hash: Indexed(str, unique=True)  # type: ignore[valid-type]
    scope: ApiKeyScope = "scanner"
    created_by: str
    created_at: datetime
    expires_at: Indexed(datetime)  # type: ignore[valid-type]
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    last_used_ip: str | None = None

    class Settings:
        name = "api_keys"
        indexes = [IndexModel([("project_id", 1), ("revoked_at", 1)])]

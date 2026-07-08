from datetime import datetime

from beanie import Document, Indexed


class ApiKey(Document):
    project_id: Indexed(str)  # type: ignore[valid-type]
    label: str
    prefix: str
    key_hash: Indexed(str, unique=True)  # type: ignore[valid-type]
    created_by: str
    created_at: datetime
    expires_at: Indexed(datetime)  # type: ignore[valid-type]
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None
    last_used_ip: str | None = None

    class Settings:
        name = "api_keys"

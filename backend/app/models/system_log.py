from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

# Operational log lines are diagnostics, not a record of who did what (that is AuditLog,
# which never expires). Bounded so a noisy failure loop cannot grow the collection forever.
SYSTEM_LOG_RETENTION_DAYS = 90


class SystemLog(Document):
    """One backend log record at WARNING or above — written by core.log_sink, never by hand."""

    level: str
    logger: str
    message: str
    #: The structlog event's extra fields (request_id, scan_id, ...), minus the ones above.
    context: dict = Field(default_factory=dict)
    exception: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "system_logs"
        # One index does both jobs: TTL expiry, and the newest-first range read (Mongo walks
        # a single-field index in either direction).
        indexes = [
            IndexModel([("created_at", 1)], expireAfterSeconds=SYSTEM_LOG_RETENTION_DAYS * 86400, name="ttl"),
        ]

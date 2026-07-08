from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: str
    actor_type: str
    actor_user_id: str | None
    action: str
    target_type: str | None
    target_id: str | None
    project_id: str | None
    metadata: dict
    ip_address: str | None
    created_at: datetime

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr


class MemberInviteRequest(BaseModel):
    email: EmailStr


class MemberRoleUpdateRequest(BaseModel):
    role: Literal["owner", "collaborator"]


class MemberResponse(BaseModel):
    id: str
    project_id: str
    user_id: str | None
    invited_email: str
    name: str | None
    role: Literal["owner", "collaborator"]
    status: Literal["pending", "accepted"]
    invited_by: str
    invited_at: datetime
    accepted_at: datetime | None

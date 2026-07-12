from typing import Literal

from pydantic import BaseModel


class UpdateUserRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = None

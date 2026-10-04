from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.schemas.auth import BcryptSafePassword


class UpdateUserRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


class RejectUserRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: BcryptSafePassword = Field(min_length=8)

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.auth import BcryptSafePassword


class UpdateUserRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None


class RejectUserRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class UpdateProfileRequest(BaseModel):
    # The email is the identity a user registered (and was approved, invited, and audited) under, so
    # it is never self-editable. Forbidding extras makes a request that tries it a 422, not a silent no-op.
    model_config = ConfigDict(extra="forbid")

    name: str | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: BcryptSafePassword = Field(min_length=8)

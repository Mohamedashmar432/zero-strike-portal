from pydantic import BaseModel, EmailStr, Field


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = None
    email: EmailStr | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

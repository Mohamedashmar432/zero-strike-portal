from pydantic import BaseModel


class UpdateUserRequest(BaseModel):
    role: str | None = None
    is_active: bool | None = None


class UpdateProfileRequest(BaseModel):
    name: str | None = None

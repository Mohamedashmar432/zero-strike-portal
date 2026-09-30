from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.core.security import validate_password_bytes

BcryptSafePassword = Annotated[str, AfterValidator(validate_password_bytes)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: BcryptSafePassword
    name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class TokenPairResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool = True


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: BcryptSafePassword = Field(min_length=8)

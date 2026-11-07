from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field

from app.core.security import validate_password_bytes

BcryptSafePassword = Annotated[str, AfterValidator(validate_password_bytes)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: BcryptSafePassword
    name: str
    invite_token: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


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
    approval_status: str = "approved"
    rejection_reason: str | None = None


REGISTER_MESSAGE = (
    "Sign-up request received. If this email already has an account, no new account was created "
    "and the existing one is unchanged; the address's owner has been notified."
)


class RegisterResponse(UserResponse):
    # Identical text for a new and an existing address, so it can state the outcome without revealing which.
    message: str = REGISTER_MESSAGE


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: BcryptSafePassword = Field(min_length=8)

from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from pydantic import BaseModel
from pymongo import IndexModel


class RefreshTokenRecord(BaseModel):
    jti: str
    token_hash: str
    issued_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str | None = None
    ip: str | None = None


class User(Document):
    email: Indexed(str, unique=True)
    password_hash: str
    name: str
    role: Literal["admin", "user"] = "user"
    is_active: bool = True
    refresh_tokens: list[RefreshTokenRecord] = []
    password_reset_token_hash: str | None = None
    password_reset_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    class Settings:
        name = "users"
        indexes = [IndexModel([("password_reset_token_hash", 1)], sparse=True)]

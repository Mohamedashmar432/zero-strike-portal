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
    # Signup gate, separate from `is_active` on purpose: "disabled" is an admin switching a
    # live account off, "pending"/"rejected" is someone who was never let in. One flag for both
    # would let the Enable toggle silently approve a signup. Existing documents have no value
    # and read back as "approved", so turning the gate on never locks anyone out.
    approval_status: Literal["approved", "pending", "rejected"] = "approved"
    rejection_reason: str | None = None
    refresh_tokens: list[RefreshTokenRecord] = []
    # Event keys (app.core.notification_events) this user wants delivered each way.
    # `None` means "never set a preference" and resolves to the catalog defaults at read
    # time — distinct from `[]`, which is someone who deliberately unsubscribed from
    # everything. Collapsing the two would silently re-subscribe them on the next default
    # change.
    notify_in_app: list[str] | None = None
    notify_email: list[str] | None = None
    password_reset_token_hash: str | None = None
    password_reset_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None

    class Settings:
        name = "users"
        indexes = [IndexModel([("password_reset_token_hash", 1)], sparse=True)]

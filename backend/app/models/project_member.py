from datetime import datetime
from typing import Literal

from beanie import Document
from pymongo import IndexModel


class ProjectMember(Document):
    project_id: str
    user_id: str | None = None
    invited_email: str
    role: Literal["owner", "collaborator"] = "collaborator"
    invited_by: str
    invited_at: datetime
    accepted_at: datetime | None = None
    # sha256 of a one-time token (see app.core.security.generate_reset_token), set only when the
    # invite was created for an email with no existing account. Proves the registrant actually
    # received the invite email rather than merely typing a matching address -- without it,
    # anyone able to register on an allowed domain could claim someone else's pending invite by
    # registering first with their email (email is never otherwise verified at signup).
    # None for an invite that resolved to an existing user at invite time (no claim step needed)
    # and for rows written before this field existed.
    invite_token_hash: str | None = None

    class Settings:
        name = "project_members"
        indexes = [
            IndexModel([("project_id", 1), ("invited_email", 1)], unique=True),
            IndexModel([("user_id", 1)]),
            # get_membership(project_id, user_id) runs on nearly every project-scoped request.
            IndexModel([("project_id", 1), ("user_id", 1)]),
        ]

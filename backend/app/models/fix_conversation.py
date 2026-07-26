"""Per-fix Ask-AI conversation (see docs/AI_AUTOFIX_DESIGN.md, Ask-AI Q&A).

A developer's read-only Q&A about a specific proposed fix, plus a record of any "change it"
revision requests. Keyed by (finding_id, scan_id) rather than proposal_id so the thread survives
a re-propose/revise (which deletes+recreates the AIFixProposal, minting a new id) — same rationale
as AIFindingInsight being keyed by fingerprint instead of the transient Finding id.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    body: str
    # Set for user messages so the team can see who asked/requested a change.
    author_user_id: str | None = None
    kind: Literal["qa", "revision"] = "qa"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FixConversation(Document):
    finding_id: str
    scan_id: str
    project_id: str
    messages: list[ConversationMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_fix_conversations"
        indexes = [
            IndexModel([("finding_id", 1), ("scan_id", 1)], unique=True),
            IndexModel([("project_id", 1)]),
        ]

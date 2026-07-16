"""AI-generated auto-fix proposal (see docs/ARCHITECTURE_REVIEW_AND_AI_ROADMAP.md).

Mirrors zero-strike-cli's SecurityRemediationAgent output shape (a confidence-gated
single-shot patch proposal). Produces a reviewable diff only -- nothing here implies or
performs a commit/PR; that policy decision is deferred to when AI Auto-Fix is built.

Schema only for now -- no service writes to this collection yet.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

AIFixProposalStatus = Literal["proposed", "applied", "dismissed"]


class AIFixProposal(Document):
    finding_id: str
    scan_id: str
    project_id: str
    status: AIFixProposalStatus = "proposed"

    # Mirrors the CLI's PatchProposal contract. Only can_fix=True with
    # confidence_score >= 80 is meant to ever surface as actionable.
    can_fix: bool = False
    confidence_score: float = 0.0
    original_code: str | None = None
    patched_code: str | None = None
    explanation: str | None = None
    patch_scope: str | None = None

    provider: str | None = None
    model_name: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_fix_proposals"
        indexes = [
            IndexModel([("finding_id", 1), ("created_at", -1)]),
            IndexModel([("scan_id", 1)]),
            IndexModel([("project_id", 1)]),
        ]

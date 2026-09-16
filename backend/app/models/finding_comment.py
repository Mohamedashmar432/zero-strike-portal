"""Team comment on a finding (see docs/AI_AUTOFIX_DESIGN.md, team controls).

A note any project member can leave on a finding so teammates reviewing the AI fix get context.
Author is stored by id only (resolved to a display email at read time) — no PII duplicated at rest.

finding_id is a snapshot of one scan's Finding row, and every rescan mints a fresh one (a new
ObjectId) even for the identical recurring issue — see models/vulnerability.py's docstring on
why Finding has no identity across scans. A comment keyed only by finding_id therefore orphaned
on every rescan: it stayed in Mongo but could never again be matched to "the same issue" once
that issue's Finding got a new id. vulnerability_id (stamped from the finding's own field, once
vulnerability_service.reconcile_scan has run) is the durable key; finding_id is kept only so
comments written before this field existed still render via the fallback read.
"""

from datetime import datetime, timezone

from beanie import Document
from pydantic import Field
from pymongo import IndexModel


class FindingComment(Document):
    finding_id: str
    scan_id: str
    project_id: str
    # None for comments predating this field, or left on a finding with no fingerprint (nothing
    # to reconcile against) — list_finding_comments falls back to finding_id for those.
    vulnerability_id: str | None = None
    author_user_id: str
    body: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_finding_comments"
        indexes = [
            IndexModel([("finding_id", 1), ("created_at", 1)]),
            IndexModel([("vulnerability_id", 1), ("created_at", 1)]),
            IndexModel([("scan_id", 1)]),
            IndexModel([("project_id", 1)]),
        ]

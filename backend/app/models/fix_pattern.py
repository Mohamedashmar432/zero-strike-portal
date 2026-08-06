"""Per-project memory of how a scanner rule was actually fixed (see docs/AI_AUTOFIX_DESIGN.md).

The next occurrence of a rule in a project should not start from zero. One row is written at each
terminal human decision on a proposal, and the most recent accepted rows for the same
(project_id, rule_id) are fed back into the next issue bundle as an example to follow.

Keyed on `rule_id` rather than `fingerprint` deliberately: a fingerprint identifies one occurrence
(and is what AIFindingInsight caches on), whereas the reusable knowledge here is "how do we fix
THIS CLASS of issue in THIS project" -- which is the rule. Finding already indexes rule_id.

Only outcome="pr_open" rows are ever read back: those passed the deterministic re-scan gate AND a
human approved them, which is the strongest signal available. Dismissals are recorded as negative
signal for analytics, never fed to a model.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

# pr_open   -> scanner-verified and human-approved; safe to hold up as an example
# dismissed -> a human rejected it; kept for analytics, never fed back into a prompt
FixOutcome = Literal["pr_open", "dismissed"]


class FixPattern(Document):
    project_id: str
    # The scanner rule this fix addressed. None for legacy findings with no rule_id -- such rows are
    # written but never match a read (reads always filter on a concrete rule_id).
    rule_id: str | None = None
    language: str | None = None
    file_path: str | None = None

    original_code: str | None = None
    patched_code: str | None = None
    explanation: str | None = None
    outcome: FixOutcome

    confidence_score: float = 0.0
    provider: str | None = None
    model_name: str | None = None
    # Incremented when this pattern is included in a later issue bundle, so a future analytics
    # view can tell which remembered fixes actually get reused.
    times_reused: int = 0

    # Traceability back to what produced the row.
    proposal_id: str | None = None
    finding_fingerprint: str | None = None
    scan_id: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_fix_patterns"
        # Plain (non-partial) indexes + app-level filtering, for the same reason AIAnalysisJob
        # documents: mongomock ignores partialFilterExpression, so a partial index can't be relied
        # on in tests. The read path is (project_id, rule_id, outcome) sorted by created_at desc.
        indexes = [
            IndexModel([("project_id", 1), ("rule_id", 1), ("created_at", -1)]),
            IndexModel([("proposal_id", 1)]),
        ]

"""Per-scan AI Auto-Fix allowance, and the requests users raise to have it lifted.

Why the quota is scoped to a SCAN and not a project: each scan is one repo at one
commit, so "you may auto-fix 10 findings here" is a bounded, meaningful budget that
refills naturally the next time that repo is scanned. A project-lifetime cap would
instead go permanently flat and block a repo that is actively being remediated.

Only the *delta* granted by an admin is stored here. The base allowance lives in
RemediationSettings.auto_fix_findings_per_scan, so raising the global default lifts
every scan at once instead of needing a backfill. Usage itself is never stored — it
is counted from AIFixProposal documents, which keeps a single source of truth and
means a counter can never drift out of sync with reality.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

AutoFixQuotaRequestStatus = Literal["pending", "approved", "rejected"]


class ScanAutoFixQuota(Document):
    """Extra auto-fix headroom an admin has granted to one scan."""

    scan_id: str
    project_id: str
    # Added on top of the global per-scan default. Accumulates across approvals.
    extra_granted: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: str | None = None

    class Settings:
        name = "scan_auto_fix_quotas"
        indexes = [
            IndexModel([("scan_id", 1)], unique=True),
            IndexModel([("project_id", 1)]),
        ]


class AutoFixQuotaRequest(Document):
    """A member asking an admin for more auto-fix headroom on a specific scan."""

    scan_id: str
    project_id: str
    requested_by: str
    # How many ADDITIONAL findings the requester wants to be able to fix.
    requested_additional: int
    # Free-text justification. Required at the API layer — an admin approving extra
    # AI spend needs to know what it is for.
    reason: str

    status: AutoFixQuotaRequestStatus = "pending"
    # An admin may grant less than was asked for, so the decision records its own
    # number rather than reusing requested_additional.
    granted_additional: int | None = None
    decision_note: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "auto_fix_quota_requests"
        indexes = [
            IndexModel([("status", 1), ("created_at", -1)]),
            IndexModel([("scan_id", 1)]),
            IndexModel([("project_id", 1)]),
            IndexModel([("requested_by", 1)]),
        ]

"""Durable, atomically-claimable AI Auto-Fix (remediation) job.

Mirrors AIAnalysisJob / Scan: a `status` + `retry_count`/`max_attempts` pair claimable via
app.core.job_queue, driven by ai_remediation_queue_service. See docs/AI_AUTOFIX_DESIGN.md.

Two kinds, one document, one queue:
- kind="propose": read-only agent generates AIFixProposal(s) for `finding_ids` (no clone).
- kind="apply":   after human approval, clones + validates + pushes a branch + opens a PR for a
  single already-approved `proposal_id`.

`scope_key` is the app-level de-duplication key (routers/ai_remediation.py looks for an active
queued/running job with the same key before inserting) -- the same pattern AIAnalysisJob uses,
and for the same reason (mongomock ignores partialFilterExpression, so a partial-unique index
can't be relied on).
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

RemediationJobKind = Literal["propose", "apply"]
RemediationJobStatus = Literal["queued", "running", "completed", "failed"]
CredentialSource = Literal["pat", "oauth"]


class RemediationJob(Document):
    kind: RemediationJobKind
    project_id: str
    scan_id: str
    # kind="propose": the findings to generate proposals for. kind="apply": empty (uses proposal_id).
    finding_ids: list[str] = Field(default_factory=list)
    # kind="apply": the AIFixProposal being applied. None for kind="propose".
    proposal_id: str | None = None
    target_ref: str = ""  # base branch to propose against / branch from
    scope_key: str  # dedup key, e.g. f"{scan_id}:{kind}:{proposal_id or hash(finding_ids)}"

    status: RemediationJobStatus = "queued"
    retry_count: int = 0
    # propose=2 (an LLM blip is safe to retry); apply=1 (a partially-applied write must NOT auto-retry).
    max_attempts: int = 2

    trace_id: str  # uuid4, bound into structlog for the whole run and stamped on every AIFixProposal
    progress_completed: int = 0  # findings proposed
    progress_total: int = 0
    provider: str | None = None
    model_name: str | None = None

    created_by: str | None = None
    # kind="apply" only: who approved the write, and which credential to re-derive at apply time
    # (the Scan's repo_token is cleared at claim time, so it can't be reused).
    approver_user_id: str | None = None
    credential_source: CredentialSource | None = None
    connection_id: str | None = None

    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_remediation_jobs"
        # See AIAnalysisJob.Settings for why this is a plain (non-partial) index + app-level dedup.
        indexes = [
            IndexModel([("status", 1), ("created_at", 1)]),  # oldest-queued claim (job_queue.claim_next)
            IndexModel([("scan_id", 1), ("status", 1)]),  # app-level active-job dedup query
        ]

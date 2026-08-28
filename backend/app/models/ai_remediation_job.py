"""Durable, atomically-claimable AI Auto-Fix (remediation) job.

Mirrors AIAnalysisJob / Scan: a `status` + `retry_count`/`max_attempts` pair claimable via
app.core.job_queue, driven by ai_remediation_queue_service. See docs/AI_AUTOFIX_DESIGN.md.

Two kinds, one document, one queue:
- kind="propose": read-only agent generates AIFixProposal(s) for `finding_ids` (no clone).
- kind="apply":   after human approval, clones + validates + pushes a branch + opens ONE PR for
  the already-approved `proposal_ids` (a batch of one for the single-proposal approve route).

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

# Observability-only sub-phase of status="running" (see RemediationJob.stage).
# propose: triage -> cloning -> proposing -> critiquing -> finalizing
#   (triage first: a job whose findings all already have proposals never clones at all)
# apply:   cloning -> baseline_scan -> patching -> rescan -> pushing -> opening_pr
RemediationJobStage = Literal[
    "cloning", "triage", "proposing", "critiquing", "finalizing",
    "baseline_scan", "patching", "rescan", "pushing", "opening_pr",
]


class RemediationJob(Document):
    kind: RemediationJobKind
    project_id: str
    scan_id: str
    # kind="propose": the findings to generate proposals for. kind="apply": empty (uses proposal_id).
    finding_ids: list[str] = Field(default_factory=list)
    # kind="apply": the AIFixProposal being applied. None for kind="propose".
    # Legacy singular form: rows written before batch apply set only this. The worker reads
    # `proposal_ids or [proposal_id]`, so both shapes run. New rows set both (proposal_id = the
    # first of the batch) so anything keying off the singular field keeps resolving.
    proposal_id: str | None = None
    # kind="apply": every proposal in this batch, in apply order. One job = one branch = one PR.
    # The job IS the batch entity (see docs/AUTOFIX_BATCH_PR.md) -- it already carries status,
    # stage, trace_id, approver and the dedup scope_key a separate batch document would duplicate.
    proposal_ids: list[str] = Field(default_factory=list)
    target_ref: str = ""  # base branch to propose against / branch from
    # kind="propose" only: a developer's "change the fix to X" instruction from the review UI. Threaded
    # (as trusted input) into the agent so the re-proposed patch honors it. None for a first proposal.
    revision_note: str | None = None
    # kind="propose" only: redraft findings that already have a proposal instead of skipping them.
    # Off by default -- a re-run over the same selection is free under the per-scan quota (already
    # charged), so without this every re-click would silently re-spend a full agent run per finding.
    force: bool = False
    scope_key: str  # dedup key, e.g. f"{scan_id}:{kind}:{proposal_id or hash(finding_ids)}"

    status: RemediationJobStatus = "queued"
    # Coarse phase within status="running", for observability only -- app.core.job_queue claims and
    # reaps on `status`, so that stays exactly as it was. Advisory: never gate logic on `stage`.
    #
    # Deliberately job-level and coarse. A propose job handles up to max_findings_per_job findings,
    # so a per-finding stage would be lying about which finding it refers to -- per-finding progress
    # is progress_completed/progress_total, and per-finding stage *artifacts* live on the
    # AIFixProposal (triage/critique/validation).
    stage: RemediationJobStage | None = None
    retry_count: int = 0
    # propose=2 (an LLM blip is safe to retry); apply=1 (a partially-applied write must NOT auto-retry).
    max_attempts: int = 2

    trace_id: str  # uuid4, bound into structlog for the whole run and stamped on every AIFixProposal
    progress_completed: int = 0  # findings proposed
    progress_total: int = 0
    # Why the run covered fewer findings than were submitted. Stored on the job (not just the
    # audit log) so the poll response can tell the user, instead of a trim happening in silence:
    #   quota_skipped     -- trimmed at trigger time by the per-scan allowance
    #   skipped_existing  -- already had a proposal, so no LLM call was spent (force=False)
    quota_skipped: int = 0
    skipped_existing: int = 0
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

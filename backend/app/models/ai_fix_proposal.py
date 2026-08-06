"""AI-generated auto-fix proposal (see docs/AI_AUTOFIX_DESIGN.md).

The durable, reviewable record of one proposed patch. Mirrors zero-strike-cli's
SecurityRemediationAgent output shape (a confidence-gated single-shot patch: can_fix,
confidence_score, original_code, patched_code, explanation, patch_scope) and is extended
with the review/apply lifecycle (review_state, branch/PR + validation metadata). A patch is
proposed read-only; branch/commit/push/PR happen only in the human-approved apply step
(ai_remediation_apply_service), never here or in the LLM loop.
"""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field
from pymongo import IndexModel

# Coarse persisted status (kept for backward compatibility). review_state below is the
# fine-grained source of truth the UI drives its badges/actions off.
AIFixProposalStatus = Literal["proposed", "applied", "dismissed"]
# proposed  -> agent produced a reviewable diff (default)
# approved  -> a human approved it; an apply job is queued
# applying  -> the apply job is cloning/validating/pushing
# validated -> patch passed the scanner re-scan gate (transient, pre-PR)
# pr_open   -> a branch was pushed and a PR opened (pr_url set)
# manual_review -> can't be safely auto-fixed/applied; manual_review_reason explains why
# dismissed -> a human dismissed it
# failed    -> the apply job errored (failure_reason explains why)
AIFixReviewState = Literal[
    "proposed", "approved", "applying", "validated", "pr_open", "manual_review", "dismissed", "failed"
]


class AIFixProposal(Document):
    finding_id: str
    scan_id: str
    project_id: str
    status: AIFixProposalStatus = "proposed"
    review_state: AIFixReviewState = "proposed"

    # Mirrors the CLI's PatchProposal contract. Only can_fix=True with confidence_score >=
    # settings.remediation_confidence_threshold (default 80) surfaces as actionable (gated at read time).
    can_fix: bool = False
    confidence_score: float = 0.0
    original_code: str | None = None
    patched_code: str | None = None
    explanation: str | None = None
    patch_scope: str | None = None
    # The single file the patch touches (relative repo path). Validated ∈ allowed_paths; the apply
    # step applies an exact-match replacement of original_code in exactly this file.
    file_path: str | None = None
    risk_notes: str | None = None
    # For SCA (dependency) findings: the version-bump context the UI renders as a picker, sourced
    # from the scanner's SCA data only (no external registry calls). Shape:
    # {package, ecosystem, current_version, available_versions[], recommended_version, manifest}.
    dependency_update: dict | None = None

    provider: str | None = None
    model_name: str | None = None
    remediation_job_id: str | None = None  # the propose job that produced this
    trace_id: str | None = None

    # Set by the apply step (kind="apply") after human approval.
    base_branch: str | None = None
    base_commit_sha: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    pr_url: str | None = None
    pr_number: int | None = None
    pr_provider: str | None = None
    # --- per-stage artifacts. Three dicts, one per pipeline stage that can independently judge
    # this proposal, so a reviewer (and a debugger) can see WHY it ended up in its review_state
    # without re-running anything. Each is None until its stage runs.
    # remediation_triage (deterministic, pre-LLM): {eligible, reason, strategy}. When
    # eligible=False no agent ran at all -- the proposal was written straight to manual_review.
    triage: dict | None = None
    # remediation_critic (one LLM call, post-draft, pre-human): {verdict, resolves_finding,
    # introduces_risk, breaks_callers, style_consistent, simpler_fix_available,
    # adjusted_confidence, issues[], reasoning, redrafted}. {"skipped": reason} when the critic
    # was disabled or its call failed -- the proposal still stands, just uncritiqued.
    critique: dict | None = None
    # Scanner re-scan gate result (deterministic, post-approval): {scope_ok, target_cleared,
    # new_finding_count, new_finding_fingerprints[], baseline_count, post_count, scanner_version,
    # ran_at}.
    validation: dict | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    manual_review_reason: str | None = None
    failure_reason: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "ai_fix_proposals"
        indexes = [
            IndexModel([("finding_id", 1), ("created_at", -1)]),
            IndexModel([("scan_id", 1)]),
            IndexModel([("project_id", 1)]),
        ]

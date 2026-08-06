"""Read/write the per-project fix memory (see models/fix_pattern.py).

Both entry points are best-effort: remembering a fix must never fail the apply job that produced
it, and a memory read must never block a fix from being proposed. Everything here swallows its own
errors and logs.
"""

import structlog

from app.models.ai_fix_proposal import AIFixProposal
from app.models.finding import Finding
from app.models.fix_pattern import FixPattern, FixOutcome

logger = structlog.get_logger(__name__)

# How many remembered fixes to show the agent. Two is enough to convey a pattern; more crowds the
# prompt with near-duplicates and pushes out the actual code under review.
_MAX_EXAMPLES = 2
# Patterns are repo code. Cap what re-enters a prompt so one huge historical patch can't dominate.
_MAX_CODE_CHARS = 2000


async def record(
    proposal: AIFixProposal, finding: Finding | None, outcome: FixOutcome
) -> FixPattern | None:
    """Remember the outcome of a human decision on a proposal. Never raises."""
    try:
        pattern = FixPattern(
            project_id=proposal.project_id,
            rule_id=finding.rule_id if finding else None,
            language=finding.language if finding else None,
            file_path=proposal.file_path,
            original_code=proposal.original_code,
            patched_code=proposal.patched_code,
            explanation=proposal.explanation,
            outcome=outcome,
            confidence_score=proposal.confidence_score,
            provider=proposal.provider,
            model_name=proposal.model_name,
            proposal_id=str(proposal.id),
            finding_fingerprint=finding.fingerprint if finding else None,
            scan_id=proposal.scan_id,
        )
        await pattern.insert()
        return pattern
    except Exception:  # noqa: BLE001 — memory is an optimization, never a failure mode
        logger.warning("could not record fix pattern", proposal_id=str(proposal.id), outcome=outcome)
        return None


def _clip(text: str | None) -> str | None:
    if not text:
        return text
    return text if len(text) <= _MAX_CODE_CHARS else text[:_MAX_CODE_CHARS] + "\n…(truncated)"


async def recent_accepted(project_id: str, rule_id: str | None) -> list[dict]:
    """The most recent scanner-verified, human-approved fixes for this rule in this project, shaped
    for the issue bundle. Empty list when there's no rule_id, no history, or anything goes wrong.

    Only outcome="pr_open" is read: those cleared the re-scan gate and a human approved them.
    Dismissed patches are deliberately not shown -- a rejected fix is not an example to follow.
    """
    if not rule_id:
        return []
    try:
        rows = (
            await FixPattern.find(
                FixPattern.project_id == project_id,
                FixPattern.rule_id == rule_id,
                FixPattern.outcome == "pr_open",
            )
            .sort(-FixPattern.created_at)
            .limit(_MAX_EXAMPLES)
            .to_list()
        )
    except Exception:  # noqa: BLE001
        logger.warning("could not read fix patterns", project_id=project_id, rule_id=rule_id)
        return []

    out: list[dict] = []
    for row in rows:
        if not row.original_code or not row.patched_code:
            continue
        out.append(
            {
                "file_path": row.file_path,
                "language": row.language,
                "original_code": _clip(row.original_code),
                "patched_code": _clip(row.patched_code),
                "explanation": _clip(row.explanation),
            }
        )
        try:
            await row.set({FixPattern.times_reused: row.times_reused + 1})
        except Exception:  # noqa: BLE001 — a reuse counter is not worth failing a proposal for
            pass
    return out

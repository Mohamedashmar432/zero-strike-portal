"""Is the AI any good? Outcome rates read back from what the Auto-Fix pipeline already stores.

ai_analytics_service answers "what did AI cost"; this answers "was it worth it": how many drafted
fixes a human accepted or dismissed, what the critic decided, whether the scanner re-scan cleared
the finding, and what one finding costs in calls, tokens and cache hits (needs AIUsageEvent.finding_id,
so rows written before it shipped are simply not counted). Read-only.
"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_usage_event import AIUsageEvent

# A human said yes: approved, or it moved on toward / into a PR.
_ACCEPTED = {"approved", "applying", "validated", "pr_open"}


def _rate(n: float, d: float) -> float | None:
    return round(n / d, 3) if d else None


async def autofix_quality(*, project_id: str | None, days: int) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    scope = {"project_id": project_id} if project_id else {}
    # ponytail: Python-side counting over one window's rows; move to a $group pipeline if a window
    # ever holds tens of thousands of proposals.
    proposals = await AIFixProposal.find({"created_at": {"$gte": since}, **scope}).to_list()
    drafted = [p for p in proposals if p.can_fix]
    # Over every critiqued proposal, not just drafted ones: a reject turns can_fix off, so counting only
    # can_fix=True would hide every reject.
    verdicts = Counter(
        "skipped" if "skipped" in p.critique else str(p.critique.get("verdict") or "none").strip().lower()
        for p in proposals
        if p.critique
    )
    accepted = sum(1 for p in drafted if p.review_state in _ACCEPTED or p.pr_state)
    dismissed = sum(1 for p in drafted if p.review_state == "dismissed")
    # A re-scan disabled by config writes {"skipped": True}; it neither cleared nor failed to clear.
    validated = [p for p in drafted if p.validation and "target_cleared" in p.validation]
    cleared = sum(1 for p in validated if p.validation.get("target_cleared"))

    events = await AIUsageEvent.find(
        {
            "created_at": {"$gte": since},
            "finding_id": {"$ne": None},
            "feature": {"$in": ["autofix", "critic"]},
            **scope,
        }
    ).to_list()
    per_finding: dict[str, list[float]] = defaultdict(lambda: [0, 0, 0.0])  # calls, tokens, cost
    for e in events:
        row = per_finding[e.finding_id]
        row[0] += 1
        row[1] += e.prompt_tokens + e.completion_tokens
        row[2] += e.cost_usd
    n = len(per_finding)
    prompt = sum(e.prompt_tokens for e in events)

    return {
        "days": days,
        "proposals": len(proposals),
        "drafted": len(drafted),
        "acceptance_rate": _rate(accepted, len(drafted)),
        "dismissal_rate": _rate(dismissed, len(drafted)),
        "rescan_cleared_rate": _rate(cleared, len(validated)),
        "merged": sum(1 for p in drafted if p.pr_state == "merged"),
        "critic_verdicts": dict(verdicts),
        "avg_calls_per_finding": round(sum(r[0] for r in per_finding.values()) / n, 2) if n else None,
        "avg_tokens_per_finding": round(sum(r[1] for r in per_finding.values()) / n, 1) if n else None,
        "avg_cost_usd_per_finding": round(sum(r[2] for r in per_finding.values()) / n, 4) if n else None,
        "cache_hit_rate": _rate(sum(e.cached_prompt_tokens for e in events), prompt),
    }

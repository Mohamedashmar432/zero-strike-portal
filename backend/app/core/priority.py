"""Deterministic finding priority score — independent of severity, boosted by OWASP
Top-10 relevance and scanner confidence. See
docs/superpowers/specs/2026-07-15-priority-scoring-and-report-templates-design.md for
the rationale behind the weights and tier boundaries.
"""

from typing import Literal

PriorityTier = Literal["critical", "high", "medium", "low"]

_SEVERITY_BASE: dict[str, float] = {
    "critical": 8.0,
    "high": 6.0,
    "medium": 4.0,
    "low": 2.0,
    "info": 0.5,
}
_OWASP_BOOST = 1.5
_CONFIDENCE_ADJ: dict[str, float] = {"high": 0.5, "low": -0.5}


def compute_priority(
    severity: str | None, owasp: list[str], confidence: str | None
) -> tuple[float, PriorityTier]:
    score = _SEVERITY_BASE.get(severity or "", 0.0)
    if owasp:
        score += _OWASP_BOOST
    score += _CONFIDENCE_ADJ.get(confidence or "", 0.0)
    score = round(max(0.0, min(10.0, score)), 1)

    tier: PriorityTier
    if score >= 8.0:
        tier = "critical"
    elif score >= 6.0:
        tier = "high"
    elif score >= 4.0:
        tier = "medium"
    else:
        tier = "low"
    return score, tier

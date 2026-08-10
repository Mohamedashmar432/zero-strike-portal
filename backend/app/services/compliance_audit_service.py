"""Turns a project's accumulated scanner findings into control-level compliance results.

Two layers, deliberately separated:

1. **A deterministic evaluator** (`evaluate`) — a pure function over a list of EvidenceItem.
   It decides every control's status. No Mongo, no LLM, no network: given the same evidence
   it always produces the same verdict, which is the whole point of a compliance artifact.
2. **An optional LLM narrator** (`_narrate_framework`) — writes explanation and remediation
   prose for controls that already failed. It never sees or sets a status, and any failure
   on its side degrades to "no prose", never to a failed audit.

The honesty rules this module enforces, because a compliance report that overstates is worse
than no report:
- A control with no selector (governance, HR, process) is `needs_manual_review`, never `pass`.
- `pass` means "the scanner detected nothing matching", and the rationale string says exactly
  that. It is not a statement that the control is implemented.
- An audit with an empty evidence set never runs — routers/compliance.py rejects it at trigger
  time, because "no scans" would otherwise render as an all-pass report.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone

import structlog
from beanie.operators import In
from pydantic import BaseModel, ValidationError

from app.core.compliance_catalog import Control, ControlSelector, Framework, get_framework
from app.core.config import settings
from app.models.compliance_audit import (
    ComplianceAudit,
    ControlEvidence,
    ControlResult,
    ControlStatus,
    FrameworkSummary,
)
from app.models.finding import Finding
from app.services import audit_service, llm_client, project_stats_service

logger = structlog.get_logger(__name__)

_SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"]


@dataclass(frozen=True)
class EvidenceItem:
    """A Finding flattened to just what control matching and evidence rendering need.

    Projecting to this (rather than passing Finding documents around) is what keeps
    `evaluate` a pure function testable without a database."""

    fingerprint: str
    scan_id: str
    rule_id: str | None
    severity: str | None
    kind: str | None
    category: str | None
    owasp: tuple[str, ...]
    cwe: tuple[str, ...]
    file: str
    line: int | None
    message: str


def _matches(selector: ControlSelector, item: EvidenceItem) -> bool:
    """Union semantics: an empty selector field is "no constraint", not "matches nothing"."""
    if selector.kinds and item.kind in selector.kinds:
        return True
    if selector.categories and item.category in selector.categories:
        return True
    if selector.owasp and any(code in selector.owasp for code in item.owasp):
        return True
    if selector.cwe and any(code in selector.cwe for code in item.cwe):
        return True
    return False


def _severity_counts(items: list[EvidenceItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        key = item.severity or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _sort_key(item: EvidenceItem) -> tuple[int, str]:
    """Worst severity first, then stable by fingerprint so a re-run of the same evidence
    persists the same sample rows."""
    order = _SEVERITY_ORDER.index(item.severity) if item.severity in _SEVERITY_ORDER else len(_SEVERITY_ORDER)
    return (order, item.fingerprint)


def _pass_rationale(total_items: int, scan_count: int) -> str:
    return (
        f"No findings matched this control's checks across {total_items} finding(s) from "
        f"{scan_count} scan(s). Absence of findings is not proof the control is implemented — "
        "it means the scanner detected nothing matching."
    )


def _fail_rationale(matched: list[EvidenceItem], counts: dict[str, int]) -> str:
    parts = [f"{counts[s]} {s}" for s in _SEVERITY_ORDER if counts.get(s)]
    breakdown = ", ".join(parts) if parts else "unrated severity"
    return f"{len(matched)} finding(s) matched this control's checks: {breakdown}."


def _partial_rationale(matched: list[EvidenceItem], fail_severities: frozenset[str]) -> str:
    bar = " or ".join(sorted(fail_severities)) or "the failing threshold"
    return (
        f"{len(matched)} finding(s) matched this control's checks, none at {bar} severity. "
        "Worth reviewing, but below the threshold this control treats as a failure."
    )


def _evaluate_control(
    control: Control,
    framework: Framework,
    items: list[EvidenceItem],
    *,
    total_items: int,
    scan_count: int,
    evidence_cap: int,
) -> ControlResult:
    base = {
        "framework": framework.key,
        "control_id": control.id,
        "control_title": control.title,
        "control_reference": control.reference,
    }

    if control.selector is None:
        return ControlResult(
            **base,
            status="needs_manual_review",
            rationale=control.manual_reason or "Cannot be assessed from source code.",
        )

    matched = [item for item in items if _matches(control.selector, item)]
    if not matched:
        return ControlResult(**base, status="pass", rationale=_pass_rationale(total_items, scan_count))

    matched.sort(key=_sort_key)
    counts = _severity_counts(matched)
    failing = any(item.severity in control.fail_severities for item in matched)
    status: ControlStatus = "fail" if failing else "partial"
    rationale = (
        _fail_rationale(matched, counts)
        if failing
        else _partial_rationale(matched, control.fail_severities)
    )
    return ControlResult(
        **base,
        status=status,
        rationale=rationale,
        evidence=[
            ControlEvidence(
                fingerprint=item.fingerprint,
                scan_id=item.scan_id,
                rule_id=item.rule_id,
                severity=item.severity,
                file=item.file,
                line=item.line,
                message=item.message,
            )
            for item in matched[:evidence_cap]
        ],
        evidence_total=len(matched),
        severity_counts=counts,
    )


def evaluate(
    framework_key: str,
    items: list[EvidenceItem],
    *,
    scan_count: int,
    evidence_cap: int,
) -> tuple[FrameworkSummary, list[ControlResult]]:
    """Deterministically evaluate every control in a framework. Pure — no I/O."""
    framework = get_framework(framework_key)
    if framework is None:
        raise ValueError(f"Unknown compliance framework: {framework_key}")

    results = [
        _evaluate_control(
            control,
            framework,
            items,
            total_items=len(items),
            scan_count=scan_count,
            evidence_cap=evidence_cap,
        )
        for control in framework.controls
    ]

    summary = FrameworkSummary(
        framework=framework.key,
        framework_title=framework.title,
        scope_note=framework.scope_note,
        controls_total=len(results),
        assessed_total=sum(1 for c in framework.controls if c.selector is not None),
        passed=sum(1 for r in results if r.status == "pass"),
        failed=sum(1 for r in results if r.status == "fail"),
        partial=sum(1 for r in results if r.status == "partial"),
        not_applicable=sum(1 for r in results if r.status == "not_applicable"),
        needs_manual_review=sum(1 for r in results if r.status == "needs_manual_review"),
    )
    return summary, results


# --- evidence gathering -------------------------------------------------------------


async def gather_evidence(audit: ComplianceAudit) -> tuple[list[EvidenceItem], list[str], bool]:
    """Load the project's findings for the audit's scope. Returns (items, scan_ids, truncated)."""
    scan_ids = await project_stats_service.resolve_scope_scan_ids(
        audit.project_id, audit.scope, audit.project_repo_ids
    )
    if not scan_ids:
        return [], [], False

    cap = settings.compliance_max_findings
    findings = (
        await Finding.find(In(Finding.scan_id, scan_ids))
        .sort("-priority_score")
        .limit(cap + 1)  # +1 so we can tell "exactly at the cap" from "over it"
        .to_list()
    )
    truncated = len(findings) > cap
    items = [
        EvidenceItem(
            fingerprint=f.fingerprint or str(f.id),
            scan_id=f.scan_id,
            rule_id=f.rule_id,
            severity=f.severity,
            kind=f.kind,
            category=f.category,
            owasp=tuple(f.owasp),
            cwe=tuple(f.cwe),
            file=f.location.file,
            line=f.location.start_line,
            message=f.message,
        )
        for f in findings[:cap]
    ]
    return items, scan_ids, truncated


# --- optional LLM narrative ---------------------------------------------------------

_NARRATIVE_SYSTEM_PROMPT = """You are a security engineer helping an engineering team understand \
why automated compliance controls were flagged by a static analysis scan.

You will receive a compliance framework name and a list of controls that a DETERMINISTIC rule \
engine has ALREADY marked as failing or partially met, together with the scanner findings that \
triggered each one.

Your job is ONLY to explain and advise. Rules:
- Do NOT re-judge, change, or comment on whether a control passes or fails. That decision is \
already made and is not yours.
- Do NOT claim the organisation is or is not compliant. You are explaining scan evidence.
- "explanation": 1-3 sentences on why these findings matter for this specific control, in plain \
language an engineer and a compliance reviewer can both read.
- "remediation": 1-3 concrete, actionable engineering steps to address the findings. No filler.
- If the evidence is too thin to say anything specific, say so plainly rather than inventing detail.

Respond with JSON only, in exactly this shape:
{"controls": [{"control_id": "<id>", "explanation": "<text>", "remediation": "<text>"}]}"""


class _ControlNarrative(BaseModel):
    control_id: str
    explanation: str = ""
    remediation: str = ""


class _NarrativeResponse(BaseModel):
    controls: list[_ControlNarrative] = []


def _clip(text: str, limit: int = 200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _narrative_payload(framework: Framework, results: list[ControlResult]) -> dict:
    return {
        "framework": framework.title,
        "controls": [
            {
                "control_id": r.control_id,
                "control_title": r.control_title,
                "status": r.status,
                "matched_findings": r.evidence_total,
                "severity_counts": r.severity_counts,
                "sample_findings": [
                    {"rule_id": e.rule_id, "severity": e.severity, "message": _clip(e.message)}
                    for e in r.evidence[:3]
                ],
            }
            for r in results
        ],
    }


async def _narrate_framework(
    framework: Framework, results: list[ControlResult], *, project_id: str
) -> str | None:
    """Attach AI explanation/remediation to the failing + partial controls in place.

    Returns a note string when the narrative could not be produced, else None. Never raises:
    a compliance result is valid without prose, and the deterministic verdicts are already
    persisted by the time this runs."""
    targets = [r for r in results if r.status in ("fail", "partial")]
    if not targets:
        return None

    capped = targets[: settings.compliance_ai_max_controls_per_call]
    messages = [
        {"role": "system", "content": _NARRATIVE_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(_narrative_payload(framework, capped))},
    ]
    try:
        raw = await llm_client.get_completion(
            messages,
            max_tokens=settings.compliance_ai_max_output_tokens,
            project_id=project_id,
            feature="compliance",
        )
        parsed = _NarrativeResponse.model_validate(raw)
    except (llm_client.LLMError, ValidationError) as exc:
        logger.warning(
            "compliance narrative unavailable", framework=framework.key, error=str(exc)[:200]
        )
        return f"AI explanations unavailable for {framework.title}: {str(exc)[:200]}"

    by_id = {r.control_id: r for r in capped}
    for entry in parsed.controls:
        target = by_id.get(entry.control_id)
        if target is None:  # model hallucinated a control id — ignore, don't fail
            continue
        target.ai_explanation = entry.explanation.strip() or None
        target.ai_remediation = entry.remediation.strip() or None

    missing = len(targets) - len(capped)
    if missing > 0:
        return (
            f"{missing} further control(s) in {framework.title} were evaluated but not sent for "
            "AI explanation (per-audit cap)."
        )
    return None


# --- the job ------------------------------------------------------------------------


async def run_job(audit: ComplianceAudit) -> None:
    now = datetime.now(timezone.utc)
    # claim_next returns the PRE-claim document, so re-assert the claimed state here or the
    # first save() below writes "queued" back over it.
    audit.status = "running"
    audit.started_at = now
    audit.updated_at = now
    audit.progress_total = len(audit.frameworks)
    audit.progress_completed = 0
    await audit.save()

    try:
        items, scan_ids, truncated = await gather_evidence(audit)
        if not scan_ids:
            # routers/compliance.py rejects this at trigger time, but the scans can still be
            # deleted (or the repo disconnected) between queueing and running. Evaluating an
            # empty evidence set would mark every code-assessable control "pass" — a clean
            # bill of health backed by nothing. Fail loudly instead.
            raise RuntimeError(
                "No completed scans in the selected scope by the time this audit ran — "
                "nothing to assess. Run a scan and start a new audit."
            )
        audit.scan_ids = scan_ids
        audit.findings_total = len(items)
        audit.findings_truncated = truncated
        # Persist the evidence set before the loop below: audit.set() re-reads the document
        # from Mongo, so anything still only in memory at that point is silently discarded.
        await audit.save()

        summaries: list[FrameworkSummary] = []
        controls: list[ControlResult] = []
        notes: list[str] = []

        for framework_key in audit.frameworks:
            framework = get_framework(framework_key)
            if framework is None:  # validated at trigger time; skip rather than fail the audit
                logger.warning("unknown framework in audit", framework=framework_key)
                continue
            summary, results = evaluate(
                framework_key,
                items,
                scan_count=len(scan_ids),
                evidence_cap=settings.compliance_max_evidence_per_control,
            )
            if audit.depth == "with_ai_narrative":
                note = await _narrate_framework(framework, results, project_id=audit.project_id)
                if note:
                    notes.append(note)
            summaries.append(summary)
            controls.extend(results)
            await audit.set(
                {
                    ComplianceAudit.progress_completed: len(summaries),
                    ComplianceAudit.updated_at: datetime.now(timezone.utc),
                }
            )

        audit.summaries = summaries
        audit.controls = controls
        audit.ai_note = " ".join(notes) if notes else None
    except Exception as exc:
        logger.exception("compliance audit failed", audit_id=str(audit.id))
        now = datetime.now(timezone.utc)
        audit.status = "failed"
        audit.error_message = str(exc)[:2000]
        audit.completed_at = now
        audit.updated_at = now
        await audit.save()
        await audit_service.record(
            "Compliance Audit Failed",
            project_id=audit.project_id,
            target_type="compliance_audit",
            target_id=str(audit.id),
            metadata={"frameworks": audit.frameworks, "error": audit.error_message},
        )
        return

    now = datetime.now(timezone.utc)
    audit.status = "completed"
    audit.completed_at = now
    audit.updated_at = now
    audit.progress_completed = len(audit.summaries)
    await audit.save()
    await audit_service.record(
        "Compliance Audit Completed",
        project_id=audit.project_id,
        target_type="compliance_audit",
        target_id=str(audit.id),
        metadata={
            "frameworks": audit.frameworks,
            "scope": audit.scope,
            "findings_total": audit.findings_total,
            "failed_controls": sum(s.failed for s in audit.summaries),
        },
    )

"""Deterministic Markdown rendering of remediation state, straight from MongoDB.

Mongo is the source of truth; Markdown here is a *generated artifact* only. Nothing in this module
persists anything, calls an LLM, or reads the repo -- given the same documents it produces the same
bytes, so it is safe to regenerate at any time and to diff two renders against each other.

Contrast with remediation_project_doc_service, which asks an LLM to summarize a clone: that output
is non-deterministic and repo-derived. This one is neither. Don't conflate them.

Two callers share render_proposal_section():
- render_scan_brief() -> the downloadable per-scan brief (includes the diff)
- ai_remediation_apply_service._apply -> the body of the PR it opens (skips the diff; the PR *is*
  the diff, but the finding detail and the re-scan evidence still belong in the description)
"""

import difflib
from datetime import datetime, timezone

from app.models.ai_finding_insight import AIFindingInsight
from app.models.ai_fix_proposal import AIFixProposal
from app.models.finding import Finding
from app.models.finding_comment import FindingComment
from app.models.project import Project
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.models.user import User

# Highest severity first, then a stable tiebreak — see _sort_key. Mirrors _SEVERITY_RANK in
# routers/ai_remediation.py.
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}

_REVIEW_STATE_LABEL = {
    "proposed": "Awaiting review",
    "approved": "Approved, apply queued",
    "applying": "Applying",
    "validated": "Validated",
    "pr_open": "PR open",
    "manual_review": "Needs manual remediation",
    "dismissed": "Dismissed",
    "failed": "Apply failed",
}


def unified_diff(original: str | None, patched: str | None, file_path: str | None) -> str | None:
    """A unified diff of a proposal's before/after. Shared with routers/ai_remediation.py (the
    /patch download endpoint) so the diff a reviewer downloads and the one in the brief are
    byte-identical."""
    if original is None or patched is None:
        return None
    fp = file_path or "file"
    diff = difflib.unified_diff(
        original.splitlines(), patched.splitlines(), fromfile=f"a/{fp}", tofile=f"b/{fp}", lineterm=""
    )
    return "\n".join(diff) or None


def _fence(text: str | None, lang: str = "") -> str:
    """Fence code without letting repo content break out of the block. A body containing ``` gets
    a longer fence rather than being escaped or truncated."""
    body = (text or "").rstrip("\n")
    ticks = "```"
    while ticks in body:
        ticks += "`"
    return f"{ticks}{lang}\n{body}\n{ticks}"


def _iso(dt: datetime | None) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if dt else "—"


def _sort_key(pair: tuple[AIFixProposal, Finding | None]) -> tuple:
    """Total order over (proposal, finding), so two renders of the same data agree. Every component
    is drawn from the documents -- never from insertion order, which Mongo does not guarantee."""
    proposal, finding = pair
    severity = (finding.severity if finding else None) or ""
    file = (finding.location.file if finding else proposal.file_path) or ""
    line = (finding.location.start_line if finding and finding.location else None) or 0
    return (
        -_SEVERITY_RANK.get(severity.lower(), -1),
        file,
        line,
        (finding.fingerprint if finding else None) or "",
        str(proposal.id),
    )


def _validation_lines(validation: dict | None) -> list[str]:
    """The deterministic re-scan evidence. This is the strongest claim the platform makes about a
    patch, so it is rendered explicitly rather than summarized."""
    if not validation:
        return []
    out = ["", "**Scanner validation**", ""]
    cleared = validation.get("target_cleared")
    out.append(
        f"- Target finding resolved on re-scan: **{'yes' if cleared else 'no'}**"
        if cleared is not None
        else "- Target finding resolved on re-scan: —"
    )
    new_count = validation.get("new_finding_count")
    if new_count is not None:
        out.append(f"- New findings introduced: **{new_count}**")
    if validation.get("scope_ok") is not None:
        out.append(f"- Changed only the proposed file: **{'yes' if validation['scope_ok'] else 'no'}**")
    for label, key in (("Baseline findings", "baseline_count"), ("Post-patch findings", "post_count")):
        if validation.get(key) is not None:
            out.append(f"- {label}: {validation[key]}")
    if validation.get("scanner_version"):
        out.append(f"- Scanner version: `{validation['scanner_version']}`")
    return out


def _stage_lines(proposal: AIFixProposal) -> list[str]:
    """Per-stage artifacts, so the brief explains *why* a proposal is in its state."""
    out: list[str] = []
    triage = proposal.triage or {}
    if triage and triage.get("eligible") is False:
        out += ["", f"**Triage** — not auto-fixable ({triage.get('strategy') or 'none'}): {triage.get('reason') or '—'}"]
    critique = proposal.critique or {}
    if critique.get("skipped"):
        out += ["", f"**AI review** — not performed ({critique['skipped']})."]
    elif critique.get("verdict"):
        bits = [f"verdict **{critique['verdict']}**"]
        if critique.get("adjusted_confidence") is not None:
            bits.append(f"reviewer confidence {critique['adjusted_confidence']:.0f}/100")
        if critique.get("redrafted"):
            bits.append("patch was redrafted once after review")
        out += ["", f"**AI review** — {', '.join(bits)}."]
        if critique.get("reasoning"):
            out.append(f"  {critique['reasoning']}")
        for issue in critique.get("issues") or []:
            out.append(f"  - {issue}")
    return out


def render_proposal_section(
    proposal: AIFixProposal,
    finding: Finding | None,
    *,
    include_diff: bool = True,
    insight: AIFindingInsight | None = None,
    comments: list[tuple[FindingComment, str]] | None = None,
    heading_level: int = 3,
) -> str:
    """One finding + its proposed fix. Self-contained so it works as a brief section AND as a PR
    description."""
    h = "#" * heading_level
    rule = (finding.rule_name if finding else None) or "Security finding"
    severity = ((finding.severity if finding else None) or "unknown").lower()
    file = (finding.location.file if finding else proposal.file_path) or "unknown file"
    line = finding.location.start_line if finding and finding.location else None
    where = f"`{file}`" + (f" line {line}" if line else "")

    lines = [f"{h} {severity.upper()} — {rule}", "", f"**Location:** {where}"]

    if finding:
        meta = []
        if finding.cwe:
            meta.append("CWE: " + ", ".join(finding.cwe))
        if finding.owasp:
            meta.append("OWASP: " + ", ".join(finding.owasp))
        if finding.fingerprint:
            meta.append(f"Fingerprint: `{finding.fingerprint}`")
        if meta:
            lines += ["", " · ".join(meta)]
        if finding.message:
            lines += ["", f"**Scanner:** {finding.message}"]
        if finding.evidence and finding.evidence[0].snippet:
            lines += ["", "**Flagged code**", "", _fence(finding.evidence[0].snippet, finding.language or "")]

    if insight and insight.explanation:
        lines += ["", "**AI analysis**", "", insight.explanation]
        if insight.is_false_positive:
            confidence = insight.false_positive_confidence
            suffix = f" (confidence {confidence:.0f}/100)" if confidence is not None else ""
            lines += [
                "",
                f"> Flagged as a likely false positive{suffix}. "
                f"{insight.verdict_reasoning or ''}".rstrip(),
            ]

    state = _REVIEW_STATE_LABEL.get(proposal.review_state, proposal.review_state)
    lines += ["", f"**Fix status:** {state} · AI confidence {proposal.confidence_score:.0f}/100"]
    if proposal.explanation:
        lines += ["", proposal.explanation]
    if proposal.manual_review_reason and not proposal.can_fix:
        lines += ["", f"**Why it needs a human:** {proposal.manual_review_reason}"]
    if proposal.risk_notes:
        lines += ["", f"**Risk notes:** {proposal.risk_notes}"]

    dep = proposal.dependency_update or {}
    if dep:
        lines += [
            "",
            f"**Dependency:** `{dep.get('package')}` {dep.get('current_version') or '?'} → "
            f"**{dep.get('recommended_version') or '?'}** in `{dep.get('manifest') or '?'}`",
        ]

    lines += _stage_lines(proposal)

    if include_diff:
        diff = unified_diff(proposal.original_code, proposal.patched_code, proposal.file_path)
        if diff:
            lines += ["", "**Proposed patch**", "", _fence(diff, "diff")]

    lines += _validation_lines(proposal.validation)

    if proposal.pr_url:
        lines += ["", f"**Pull request:** {proposal.pr_url}"]
    if proposal.failure_reason:
        lines += ["", f"**Apply failed:** {proposal.failure_reason}"]

    if comments:
        lines += ["", "**Discussion**", ""]
        for comment, author in comments:
            lines.append(f"- _{author}_ ({_iso(comment.created_at)}): {comment.body}")

    return "\n".join(lines)


async def _authors(comments: list[FindingComment]) -> dict[str, str]:
    """Display names for comment authors. Mirrors routers/ai_remediation._users_map: resolve each id
    independently inside try/except, because a stale or malformed author_user_id must degrade to
    "Unknown" for that one comment rather than failing the whole brief."""
    out: dict[str, str] = {}
    for uid in {c.author_user_id for c in comments if c.author_user_id}:
        try:
            user = await User.get(uid)
        except Exception:  # noqa: BLE001 — unparseable id: fall through to Unknown
            user = None
        if user is not None:
            out[uid] = user.name or user.email or "Unknown"
    return out


async def render_scan_brief(scan_id: str, *, generated_at: datetime | None = None) -> str | None:
    """The full remediation brief for one scan. Returns None when the scan doesn't exist.

    Deterministic apart from the single generated-at line in the header: identical documents
    produce identical bytes, so regenerating is safe and two renders can be diffed directly.
    """
    scan = await Scan.get(scan_id)
    if scan is None:
        return None
    project = await Project.get(scan.project_id)
    repo = await ProjectRepo.get(scan.project_repo_id) if scan.project_repo_id else None

    proposals = await AIFixProposal.find(AIFixProposal.scan_id == scan_id).to_list()
    findings = await Finding.find(Finding.scan_id == scan_id).to_list()
    fmap = {str(f.id): f for f in findings}

    insights = await AIFindingInsight.find(AIFindingInsight.project_id == scan.project_id).to_list()
    imap = {i.fingerprint: i for i in insights}

    comments = await FindingComment.find(FindingComment.scan_id == scan_id).to_list()
    authors = await _authors(comments)
    cmap: dict[str, list[tuple[FindingComment, str]]] = {}
    for c in sorted(comments, key=lambda c: (c.created_at, str(c.id))):
        cmap.setdefault(c.finding_id, []).append((c, authors.get(c.author_user_id, "Unknown")))

    pairs = sorted(((p, fmap.get(p.finding_id)) for p in proposals), key=_sort_key)

    head = [
        f"# Remediation brief — {project.name if project else 'Unknown project'}",
        "",
        f"_Generated {_iso(generated_at or datetime.now(timezone.utc))} from ZeroStrike scan `{scan_id}`._",
        "",
        "## Scan",
        "",
        f"- Repository: {repo.repo_full_name if repo else (scan.repo_url or '—')}",
        f"- Branch: `{scan.branch or '—'}`",
        f"- Commit: `{scan.git_commit or '—'}`",
        f"- Scan type: {scan.scan_type}",
        f"- Scanner version: `{scan.scanner_version or '—'}`",
        f"- Completed: {_iso(scan.completed_at)}",
        "",
        "## Summary",
        "",
        f"- Findings in this scan: **{len(findings)}**",
        f"- Fix proposals generated: **{len(proposals)}**",
    ]

    # Counted off review_state, the same field the UI drives its badges from, so the brief and the
    # review screen can never disagree. Deliberately NOT re-deriving the confidence-threshold
    # buckets the API computes -- each proposal's own confidence and state are listed below, so a
    # second definition of "fixable" would only be a thing to drift.
    by_state: dict[str, int] = {}
    for proposal in proposals:
        by_state[proposal.review_state] = by_state.get(proposal.review_state, 0) + 1
    for state in sorted(by_state):
        head.append(f"- {_REVIEW_STATE_LABEL.get(state, state)}: **{by_state[state]}**")

    if not pairs:
        head += ["", "## Findings", "", "_No fix proposals have been generated for this scan yet._", ""]
        return "\n".join(head)

    body = ["", "## Findings and proposed fixes", ""]
    for proposal, finding in pairs:
        insight = imap.get(finding.fingerprint) if finding and finding.fingerprint else None
        body.append(
            render_proposal_section(
                proposal, finding,
                include_diff=True,
                insight=insight,
                comments=cmap.get(proposal.finding_id),
            )
        )
        body.append("")

    return "\n".join(head + body).rstrip("\n") + "\n"

"""Core AI Analysis logic: per-finding enrichment (grouped by rule_id, one LLM call per
group rather than per finding) and scan-level synthesis, plus the entry point the AI job
queue (ai_job_queue_service) invokes after claiming a job.

Findings are grouped by rule_id because the same scanner rule firing across many files
is the same underlying judgment call -- one LLM call per rule_id group is both cheaper
and more consistent than one per finding.
"""

import asyncio
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import NamedTuple

import structlog
from beanie.operators import In
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.core.retry import retry_transient
from app.core.timeutils import as_utc
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.ai_finding_insight import AIFindingInsight
from app.models.ai_scan_insight import AIScanInsight
from app.models.finding import Finding
from app.models.scan import Scan
from app.services import ai_provider_config_service, audit_service, llm_client

logger = structlog.get_logger(__name__)

_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_JOB_STATUS_TO_API = {"queued": "queued", "running": "in_progress", "completed": "completed", "failed": "failed"}


class ScanAiStatus(NamedTuple):
    status: str | None
    started_at: datetime | None
    progress_completed: int
    progress_total: int


async def latest_scan_ai_status(scan_ids: list[str]) -> dict[str, ScanAiStatus]:
    """One batch query for the newest scan-level AIAnalysisJob per scan id, so any list/detail
    view (scan list, scan detail, dashboard) can show an "AI analyzing · N%" tag without a
    per-row round trip. started_at + progress are only meaningful while queued/running. Shared by
    routers/scans.py and services/dashboard_service.py -- one source of truth for the join."""
    if not scan_ids:
        return {}
    jobs = (
        await AIAnalysisJob.find(AIAnalysisJob.kind == "scan", In(AIAnalysisJob.scope_key, scan_ids))
        .sort("-created_at")
        .to_list()
    )
    latest: dict[str, ScanAiStatus] = {}
    for j in jobs:
        if j.scope_key in latest:
            continue  # already captured the newest for this scan
        active = j.status in ("queued", "running")
        latest[j.scope_key] = ScanAiStatus(
            status=_JOB_STATUS_TO_API.get(j.status),
            started_at=as_utc(j.started_at or j.created_at) if active else None,
            progress_completed=j.progress_completed if active else 0,
            progress_total=j.progress_total if active else 0,
        )
    return latest

# Findings a deterministic scanner already produced -- the AI's job is to judge/enrich them,
# never to invent additional ones. The schema is stated IN the prompt (not enforced via
# response_format) because local/OpenAI-compatible models often reject response_format and
# rarely guess an unstated shape -- llm_client parses the reply tolerantly (see _extract_json).
_ENRICH_SYSTEM_PROMPT = (
    "You are a senior application security engineer. A deterministic scanner has ALREADY produced "
    "the findings given to you. Your job is to judge and enrich each one — never invent new "
    "findings, never drop any.\n\n"
    "Return ONLY a JSON object (no prose, no markdown fences) of exactly this shape:\n"
    "{\n"
    '  "findings": [\n'
    "    {\n"
    '      "fingerprint": "<echo this finding\'s fingerprint EXACTLY>",\n'
    '      "owasp": ["A03:2021 - Injection"],\n'
    '      "cwe": ["CWE-89"],\n'
    '      "cvss_score": 7.5,\n'
    '      "explanation": "why this is or is not actually exploitable",\n'
    '      "is_false_positive": false,\n'
    '      "false_positive_confidence": 0.0,\n'
    '      "analysis_confidence": 0.85,\n'
    '      "verdict_reasoning": "one sentence justifying the verdict",\n'
    '      "improved_description": "a clearer description of the issue",\n'
    '      "adjusted_severity": null,\n'
    '      "severity_reasoning": null\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Rules:\n"
    "0. analysis_confidence is YOUR confidence in this verdict/enrichment, from 0.0 to 1.0 "
    "(distinct from false_positive_confidence). Always provide it.\n"
    "1. Output exactly one object per finding, each echoing its fingerprint verbatim.\n"
    "2. adjusted_severity MUST be one of critical, high, medium, low, info — or null when the "
    "scanner's severity is already correct. Only change it when the scanner is clearly wrong: "
    "downgrade an obvious false positive or over-rating, upgrade a clear under-rating. When you "
    "set it, add a one-sentence severity_reasoning; otherwise leave both null.\n"
    "3. When unsure about a field use null (or [] for lists). Never omit a finding."
)

_SYNTHESIS_SYSTEM_PROMPT = (
    "You summarize a security scan's already-computed, per-finding AI insights into one "
    "concise report. You do not re-judge individual findings -- that judgment already happened."
)


class _FindingEnrichment(BaseModel):
    """Fields matching AIFindingInsight's enrichment fields -- strict validation boundary
    between whatever JSON the LLM returned and what we're willing to persist."""

    fingerprint: str
    owasp: list[str] = Field(default_factory=list)
    cwe: list[str] = Field(default_factory=list)
    cvss_score: float | None = None
    explanation: str | None = None
    is_false_positive: bool | None = None
    false_positive_confidence: float | None = None
    analysis_confidence: float | None = None
    verdict_reasoning: str | None = None
    improved_description: str | None = None
    # Loose here (normalized to a valid severity or None at persist time) so a sloppy value from a
    # local model drops only the override, not the whole finding's enrichment.
    adjusted_severity: str | None = None
    severity_reasoning: str | None = None


class _ScanSynthesisResponse(BaseModel):
    summary: str
    top_recommendations: list[str] = Field(default_factory=list)


def _clip(text: str | None, limit: int = 300) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def _finding_payload(finding: Finding) -> dict:
    # Deliberately compact -- long fields are clipped and raw evidence/code blobs are dropped
    # (only a file:line locator is kept). A small local model has a tiny context window, and a
    # rule group of dozens of findings must still fit in one batch. Mirrors zero-strike-cli's
    # trimmed enrichment payload (description truncated, no evidence snippets).
    loc = finding.location
    return {
        "rule_id": finding.rule_id,
        "message": _clip(finding.message),
        "file": loc.file if loc else None,
        "line": loc.start_line if loc else None,
        "severity": finding.severity,
        "cwe": finding.cwe,
        "owasp": finding.owasp,
        "rationale": _clip(finding.rationale),
        "remediation": _clip(finding.remediation),
    }


def _parse_enrichments(raw: dict) -> dict[str, _FindingEnrichment]:
    """Validate each returned finding independently and key by fingerprint. A single malformed
    entry is skipped, not fatal -- the rest of the chunk still lands (mirrors the CLI's
    never-lose-the-others philosophy). Raises only when the top-level shape isn't usable at all."""
    items = raw.get("findings") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise llm_client.LLMMalformedResponseError(
            f"LLM response had no 'findings' list (got keys {list(raw)[:5] if isinstance(raw, dict) else type(raw)})"
        )
    by_fingerprint: dict[str, _FindingEnrichment] = {}
    for entry in items:
        try:
            item = _FindingEnrichment.model_validate(entry)
        except ValidationError:
            continue  # skip one malformed entry; keep the rest of the chunk
        by_fingerprint[item.fingerprint] = item
    return by_fingerprint


def _representative(members: list[Finding]) -> Finding:
    """The highest-severity member of a rule group -- the one finding we actually send to the LLM
    for the whole group. Its verdict is fanned out to every member (see zero-strike-cli's
    per-rule enrichment). Same vulnerability across N files = one LLM call, applied to all N."""
    return min(members, key=lambda f: _SEV_ORDER.get((f.severity or "").lower(), 9))


async def _persist_insight(
    finding: Finding, item: _FindingEnrichment, config, similar_finding_count: int, now: datetime
) -> AIFindingInsight:
    """Upsert one AIFindingInsight (keyed by fingerprint, project_id) from a rule's enrichment.
    Called once per finding in the group -- the rule's single verdict copied onto each occurrence."""
    insight = await AIFindingInsight.find_one(
        AIFindingInsight.fingerprint == finding.fingerprint,
        AIFindingInsight.project_id == finding.project_id,
    )
    if insight is None:
        insight = AIFindingInsight(fingerprint=finding.fingerprint, project_id=finding.project_id)
    insight.owasp = item.owasp
    insight.cwe = item.cwe
    insight.cvss_score = item.cvss_score
    insight.explanation = item.explanation
    insight.is_false_positive = item.is_false_positive
    insight.false_positive_confidence = item.false_positive_confidence
    insight.analysis_confidence = item.analysis_confidence
    insight.verdict_reasoning = item.verdict_reasoning
    insight.improved_description = item.improved_description
    # Normalize the AI severity overlay: keep it only if it's a real severity level,
    # otherwise drop the override (and its reasoning) rather than trusting a sloppy value.
    adjusted = (item.adjusted_severity or "").strip().lower() or None
    insight.adjusted_severity = adjusted if adjusted in _SEVERITIES else None
    insight.severity_reasoning = item.severity_reasoning if insight.adjusted_severity else None
    insight.similar_finding_count = similar_finding_count
    insight.provider = config.provider if config else None
    insight.model_name = config.model_name if config else None
    insight.updated_at = now
    await insight.save()
    return insight


@retry_transient((llm_client.LLMMalformedResponseError,), max_attempts=2, base_delay=1.0)
async def _enrich_completion(messages: list[dict]) -> dict:
    """One enrichment call, capped by max_tokens so a small local model can't run past its own
    output limit mid-JSON and truncate. A malformed/garbled response is retried once (the model
    often produces valid JSON on a second pass) before it counts as a coverage gap."""
    return await llm_client.get_completion(messages, max_tokens=settings.ai_analysis_max_output_tokens)


async def _group_cached(members: list[Finding], project_id: str) -> list[AIFindingInsight] | None:
    """If every fingerprinted member already has an insight, return them (no LLM call needed).
    A single missing member returns None so the whole group is re-enriched -- which is exactly
    what makes a partial run re-runnable: rerun with force=False backfills only the gaps."""
    fingerprinted = [m for m in members if m.fingerprint]
    if not fingerprinted:
        return []  # nothing keyable in this group -- treat as resolved, no insight to store
    cached: list[AIFindingInsight] = []
    for f in fingerprinted:
        existing = await AIFindingInsight.find_one(
            AIFindingInsight.fingerprint == f.fingerprint, AIFindingInsight.project_id == project_id
        )
        if existing is None:
            return None
        cached.append(existing)
    return cached


async def _enrich_group_chunk(
    semaphore: asyncio.Semaphore,
    chunk_groups: list[tuple[str, list[Finding]]],
    project_id: str,
    config,
) -> tuple[list[AIFindingInsight], int]:
    """Enrich up to batch_size RULE GROUPS in one LLM call: send one representative per group,
    then fan each rule's verdict out to every member of its group. Returns (saved insights,
    number of groups actually covered) -- a group whose representative the model omitted is a
    coverage gap this round (not a silent drop; it's re-runnable). Findings without a fingerprint
    can't be keyed into AIFindingInsight, so they're skipped."""
    async with semaphore:
        rep_to_group: dict[str, list[Finding]] = {}
        payload_reps: list[dict] = []
        for rule_id, members in chunk_groups:
            fp_members = [m for m in members if m.fingerprint]
            if not fp_members:
                continue
            rep = _representative(fp_members)
            rep_to_group[rep.fingerprint] = fp_members
            payload_reps.append({"fingerprint": rep.fingerprint, "rule_id": rule_id, **_finding_payload(rep)})
        if not payload_reps:
            return [], 0

        messages = [
            {"role": "system", "content": _ENRICH_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({"findings": payload_reps})},
        ]
        raw = await _enrich_completion(messages)
        by_fingerprint = _parse_enrichments(raw)

        now = datetime.now(timezone.utc)
        saved: list[AIFindingInsight] = []
        covered = 0
        for rep_fp, fp_members in rep_to_group.items():
            item = by_fingerprint.get(rep_fp)
            if item is None:
                continue  # rep omitted -> whole group left for a re-run to backfill
            covered += 1
            similar = len(fp_members) - 1  # other files/locations with this same rule
            for member in fp_members:
                saved.append(await _persist_insight(member, item, config, similar, now))
        return saved, covered


async def analyze_findings_batch(
    findings: list[Finding], *, force: bool = False, progress_cb=None
) -> list[AIFindingInsight]:
    """Groups findings by rule_id and enriches ONE representative per group, fanning that verdict
    out to every member (same vulnerability across N files = one LLM call, applied to all N, each
    tagged with how many siblings it has). Representatives are chunked into provider-sized batches
    so even hundreds of distinct rules stay within the model's context, and chunks run concurrently.

    Partial-tolerant: a rule group whose representative fails or is omitted is a coverage GAP, not a
    silent success -- the caller (synthesize_scan) records analyzed-vs-intended, and a re-run
    (force=False) backfills only the gaps. Only if *every* chunk errors do we re-raise, so a wholly
    broken provider marks the job failed rather than "completed with 0 findings".

    progress_cb (optional async callable(completed, total)) reports RULE GROUPS resolved (cached or
    enriched) out of total groups -- it advances only on real coverage, never on a mere attempt."""
    if not findings:
        return []
    project_id = findings[0].project_id
    # Only needed for batch sizing + stamping provider/model. Don't hard-fail if absent: a fully-cached
    # batch short-circuits without any LLM call, and an actual enrichment call raises
    # LLMNotConfiguredError from get_completion itself when there's no provider.
    config = await ai_provider_config_service.get_active_config()
    batch_size = (
        settings.ai_analysis_local_batch_size
        if config is not None and config.provider in settings.ai_analysis_local_providers
        else settings.ai_analysis_cloud_batch_size
    )

    groups: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        groups[f.rule_id or "unknown"].append(f)
    group_items = list(groups.items())

    total = len(group_items)  # progress is measured in rule groups, not raw findings
    completed = 0
    if progress_cb:
        await progress_cb(0, total)

    all_insights: list[AIFindingInsight] = []
    to_enrich: list[tuple[str, list[Finding]]] = []

    # Cache pass: fully-cached groups resolve with no LLM call (and count toward progress).
    for rule_id, members in group_items:
        if not force:
            cached = await _group_cached(members, project_id)
            if cached is not None:
                all_insights.extend(cached)
                completed += 1
                if progress_cb:
                    await progress_cb(completed, total)
                continue
        to_enrich.append((rule_id, members))

    chunks = [to_enrich[i : i + batch_size] for i in range(0, len(to_enrich), batch_size)]
    semaphore = asyncio.Semaphore(settings.ai_analysis_concurrency)

    async def _run(chunk_groups: list[tuple[str, list[Finding]]]):
        nonlocal completed
        insights, covered = await _enrich_group_chunk(semaphore, chunk_groups, project_id, config)
        completed += covered  # advance only by groups actually enriched (honest partial signal)
        if progress_cb:
            await progress_cb(completed, total)
        return insights

    results = await asyncio.gather(*(_run(c) for c in chunks), return_exceptions=True)

    errors = [r for r in results if isinstance(r, Exception)]
    for r in results:
        if not isinstance(r, Exception):
            all_insights.extend(r)
    for err in errors:
        logger.warning("ai analysis chunk failed", error=str(err))
    if chunks and len(errors) == len(chunks):
        raise errors[0]  # every enrichment chunk failed -- surface the real upstream error
    return all_insights


async def analyze_finding(finding: Finding, *, force: bool = False) -> AIFindingInsight:
    """Single-finding convenience wrapper over analyze_findings_batch (one group, one rep call)."""
    if not finding.fingerprint:
        raise ValueError("Finding has no fingerprint; cannot run AI analysis")
    insights = await analyze_findings_batch([finding], force=force)
    for insight in insights:
        if insight.fingerprint == finding.fingerprint:
            return insight
    raise llm_client.LLMMalformedResponseError(
        f"LLM response did not include an entry for fingerprint {finding.fingerprint!r}"
    )


async def synthesize_scan(
    scan: Scan, insights: list[AIFindingInsight], *, intended: int | None = None
) -> AIScanInsight:
    """Reduces the already-computed AIFindingInsight list into one AIScanInsight -- one
    additional summarization LLM call, not a second full analysis pass.

    `intended` is how many findings the job set out to analyze; `total` (len(insights)) is how many
    actually got an insight. When intended > total, coverage was partial and the summary says so --
    the UI shows "Analyzed X of Y" instead of pretending the truncated count is the whole scan."""
    total = len(insights)
    intended = intended if intended is not None else total
    false_positive_count = sum(1 for i in insights if i.is_false_positive)

    config = await ai_provider_config_service.get_active_config()
    if config is None:
        raise llm_client.LLMNotConfiguredError("No active AI provider configured")
    now = datetime.now(timezone.utc)

    existing = await AIScanInsight.find_one(AIScanInsight.scan_id == str(scan.id))
    if existing is None:
        existing = AIScanInsight(scan_id=str(scan.id), project_id=scan.project_id)

    if not insights:
        existing.summary = (
            "No findings were analyzed." if not intended
            else f"None of the {intended} findings could be analyzed — the AI provider returned no "
            "usable results. Re-run analysis to try again."
        )
        existing.total_findings_intended = intended
        existing.total_findings_analyzed = 0
        existing.false_positive_count = 0
        existing.top_recommendations = []
        existing.provider = config.provider
        existing.model_name = config.model_name
        existing.updated_at = now
        await existing.save()
        return existing

    messages = [
        {"role": "system", "content": _SYNTHESIS_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "total_findings_analyzed": total,
                    "false_positive_count": false_positive_count,
                    "insights": [
                        {
                            "cwe": i.cwe,
                            "owasp": i.owasp,
                            "cvss_score": i.cvss_score,
                            "is_false_positive": i.is_false_positive,
                            "explanation": _clip(i.explanation, 200),
                        }
                        for i in insights
                    ],
                }
            ),
        },
    ]
    coverage = f"{total} of {intended}" if intended > total else f"{total}"
    # The per-finding insights are already persisted by this point; a failed summary must NOT
    # fail the whole scan job. Validate before mutating `existing`, and fall back to a computed
    # summary on ANY LLM error (malformed JSON, wrong shape, or a permanent error such as a
    # small local model exceeding its context on the summary prompt).
    try:
        raw = await llm_client.get_completion(messages)
        parsed = _ScanSynthesisResponse.model_validate(raw)
        summary = parsed.summary
        recommendations = parsed.top_recommendations
    except (llm_client.LLMError, ValidationError):
        logger.warning("scan synthesis response unusable; using computed fallback", scan_id=str(scan.id))
        summary = (
            f"Analyzed {coverage} findings; {false_positive_count} flagged as likely false positives. "
            "See the enriched findings below."
        )
        recommendations = []
    # Prepend a partial-coverage note even to a model-written summary, so an incomplete run never
    # reads as a full one (re-run to backfill the rest -- cached insights make it cheap).
    if intended > total:
        summary = f"Analyzed {coverage} findings (re-run to analyze the rest). {summary}"

    existing.summary = summary
    existing.total_findings_intended = intended
    existing.total_findings_analyzed = total
    existing.false_positive_count = false_positive_count
    existing.top_recommendations = recommendations
    existing.provider = config.provider
    existing.model_name = config.model_name
    existing.updated_at = now
    await existing.save()
    return existing


async def run_job(job: AIAnalysisJob) -> None:
    """Entry point invoked by ai_job_queue_service after claiming a job. Always ends by
    writing the job to a terminal status -- a malformed/permanent LLM failure must never
    leave a job stuck "running" nor partially write/corrupt an existing insight (insights
    are only ever mutated after their LLM response validates, see _analyze_chunk/synthesize_scan)."""
    # Stamp when work actually began so the UI can show an "analyzing since…" elapsed tag
    # (started_at was previously never set). claim_next returns the pre-claim document
    # (status still "queued"), so we must also set status="running" here before saving --
    # otherwise this save would clobber the DB's "running" back to "queued".
    start = datetime.now(timezone.utc)
    job.status = "running"
    job.started_at = start
    job.updated_at = start
    await job.save()
    try:
        if job.kind == "finding":
            finding = await Finding.find_one(
                Finding.fingerprint == job.fingerprint, Finding.project_id == job.project_id
            )
            if finding is None:
                raise ValueError(f"Finding not found for fingerprint={job.fingerprint!r}")
            await analyze_finding(finding, force=job.force)
        else:
            scan = await Scan.get(job.scan_id)
            if scan is None:
                raise ValueError(f"Scan not found: {job.scan_id!r}")
            findings = (
                await Finding.find(Finding.scan_id == job.scan_id)
                .sort("-priority_score")
                .limit(settings.ai_analysis_max_findings_per_scan)
                .to_list()
            )

            async def _progress(done: int, total: int) -> None:
                # Surgical $set so concurrent chunk callbacks don't clobber other job fields.
                await job.set(
                    {
                        AIAnalysisJob.progress_completed: done,
                        AIAnalysisJob.progress_total: total,
                        AIAnalysisJob.updated_at: datetime.now(timezone.utc),
                    }
                )

            insights = await analyze_findings_batch(findings, force=job.force, progress_cb=_progress)
            await synthesize_scan(scan, insights, intended=len(findings))
    except Exception as exc:
        logger.exception("ai analysis job failed", job_id=str(job.id), kind=job.kind)
        now = datetime.now(timezone.utc)
        job.status = "failed"
        job.error_message = str(exc)[:2000]
        job.completed_at = now
        job.updated_at = now
        await job.save()
        await audit_service.record(
            "AI Analysis Job Failed",
            project_id=job.project_id,
            target_type="ai_analysis_job",
            target_id=str(job.id),
            metadata={"kind": job.kind, "scope_key": job.scope_key, "error": job.error_message},
        )
        return

    now = datetime.now(timezone.utc)
    job.status = "completed"
    job.completed_at = now
    job.updated_at = now
    await job.save()
    await audit_service.record(
        "AI Analysis Job Completed",
        project_id=job.project_id,
        target_type="ai_analysis_job",
        target_id=str(job.id),
        metadata={"kind": job.kind, "scope_key": job.scope_key},
    )

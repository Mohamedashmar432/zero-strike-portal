"""Propose-phase orchestration for AI Auto-Fix (see docs/AI_AUTOFIX_DESIGN.md).

Entry point ai_remediation_queue_service invokes after claiming a kind="propose" RemediationJob.
Mirrors ai_analysis_service.run_job: flip to running, do the work, always end in a terminal status
and record an audit event. For each target finding it builds a bounded, secret-redacted issue
bundle, runs the read-only agent (wall-clock-bounded), and persists one AIFixProposal. A single
difficult finding never fails the whole job (the agent returns a can_fix=False proposal instead);
only a hard, job-wide condition (no active provider) fails the job.
"""

import asyncio
from datetime import datetime, timezone

import structlog

from app.core.config import settings
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.finding import Finding
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from app.services import (
    ai_provider_config_service,
    ai_remediation_agent,
    audit_service,
    llm_client,
    secret_redaction,
)
from app.services.remediation_tools import SubmitFixProposalArgs, ToolContext

logger = structlog.get_logger(__name__)


def _issue_bundle(finding: Finding, redacted_snippet: str | None) -> dict:
    loc = finding.location
    taint = None
    if finding.taint_context:
        taint = {
            "source_var": finding.taint_context.source_var,
            "source_expr": finding.taint_context.source_expr,
            "sink": finding.taint_context.sink,
        }
    return {
        "finding_id": str(finding.id),
        "fingerprint": finding.fingerprint,
        "rule_id": finding.rule_id,
        "rule_name": finding.rule_name,
        "kind": finding.kind,
        "severity": finding.severity,
        "message": finding.message,
        "location": {"file": loc.file, "start_line": loc.start_line, "end_line": loc.end_line},
        "language": finding.language,
        "evidence_snippet": redacted_snippet,
        "taint_context": taint,
        "cwe": finding.cwe,
        "owasp": finding.owasp,
        "rationale": finding.rationale,
        "scanner_remediation": finding.remediation,
    }


def _redacted_snippet(finding: Finding) -> str | None:
    ev = finding.evidence[0] if finding.evidence else None
    snippet = ev.snippet if ev else None
    if not snippet:
        return None
    # For a secret finding the snippet IS the secret -- blank every line deterministically.
    known = set(range(1, len(snippet.splitlines()) + 1)) if finding.kind == "secret" else None
    return secret_redaction.redact(snippet, known)


async def _propose_for_finding(
    finding: Finding, job: RemediationJob, branch: str, provider: str | None, model: str | None
) -> AIFixProposal:
    redacted = _redacted_snippet(finding)
    loc = finding.location
    ctx = ToolContext(
        provider=provider or "",
        repo_full_name="",
        branch=branch,
        allowed_paths=[loc.file] if loc.file else [],
        project_id=job.project_id,
        scan_id=job.scan_id,
        trace_id=job.trace_id,
        finding_context={
            "finding_id": str(finding.id),
            "file_path": loc.file,
            "language": finding.language,
            "original_code": redacted or "",
            "start_line": loc.start_line,
            "end_line": loc.end_line,
        },
    )
    try:
        result = await asyncio.wait_for(
            ai_remediation_agent.run_agent(
                _issue_bundle(finding, redacted), ctx, ai_remediation_agent.budgets_from_settings()
            ),
            timeout=settings.remediation_agent_wall_clock_seconds,
        )
    except (asyncio.TimeoutError, llm_client.LLMError) as exc:
        logger.warning("remediation agent failed for finding", finding_id=str(finding.id), error=str(exc))
        result = SubmitFixProposalArgs(
            finding_id=str(finding.id),
            can_fix=False,
            confidence_score=0.0,
            file_path=loc.file or "",
            explanation=f"Fix generation did not complete: {exc}",
            patch_scope="none",
        )

    review_state = "proposed" if result.can_fix else "manual_review"
    manual_reason = None if result.can_fix else (result.explanation or "Not safely auto-fixable.")

    # Idempotent re-trigger: replace any prior proposal for this finding in this scan.
    await AIFixProposal.find(
        AIFixProposal.finding_id == str(finding.id), AIFixProposal.scan_id == job.scan_id
    ).delete()
    proposal = AIFixProposal(
        finding_id=str(finding.id),
        scan_id=job.scan_id,
        project_id=job.project_id,
        status="proposed",
        review_state=review_state,
        can_fix=result.can_fix,
        confidence_score=result.confidence_score,
        original_code=result.original_code,
        patched_code=result.patched_code,
        explanation=result.explanation,
        patch_scope=result.patch_scope,
        file_path=result.file_path,
        risk_notes=result.risk_notes,
        provider=provider,
        model_name=model,
        remediation_job_id=str(job.id),
        trace_id=job.trace_id,
        base_branch=branch,
        manual_review_reason=manual_reason,
    )
    await proposal.insert()
    return proposal


async def run_job(job: RemediationJob) -> None:
    start = datetime.now(timezone.utc)
    job.status = "running"
    job.started_at = start
    job.updated_at = start
    await job.save()
    structlog.contextvars.bind_contextvars(trace_id=job.trace_id, remediation_job_id=str(job.id))
    try:
        config = await ai_provider_config_service.get_active_config()
        if config is None or not await ai_provider_config_service.is_ready(config):
            raise ValueError("No AI provider is configured and active")
        provider, model = config.provider, config.model_name

        # Propose has no clone, so a missing/unresolvable Scan doc isn't fatal -- it only informs
        # the base branch we record for the later apply step. Default to "main" otherwise.
        try:
            scan = await Scan.get(job.scan_id)
        except Exception:
            scan = None
        repo = None
        if scan is not None and scan.project_repo_id:
            repo = await ProjectRepo.get(scan.project_repo_id)
        branch = job.target_ref or (repo.selected_branch if repo else None) or "main"

        findings: list[Finding] = []
        for fid in job.finding_ids[: settings.remediation_max_findings_per_job]:
            try:
                f = await Finding.get(fid)
            except Exception:
                f = None
            if f is not None:
                findings.append(f)

        await job.set({RemediationJob.progress_total: len(findings), RemediationJob.updated_at: datetime.now(timezone.utc)})
        fixable = 0
        for done, finding in enumerate(findings, start=1):
            proposal = await _propose_for_finding(finding, job, branch, provider, model)
            if proposal.can_fix:
                fixable += 1
            await job.set(
                {RemediationJob.progress_completed: done, RemediationJob.updated_at: datetime.now(timezone.utc)}
            )
    except Exception as exc:
        logger.exception("remediation propose job failed", job_id=str(job.id))
        now = datetime.now(timezone.utc)
        job.status = "failed"
        job.error_message = str(exc)[:2000]
        job.completed_at = now
        job.updated_at = now
        await job.save()
        await audit_service.record(
            "AI Fix Proposals Failed",
            project_id=job.project_id,
            target_type="remediation_job",
            target_id=str(job.id),
            metadata={"scan_id": job.scan_id, "error": job.error_message},
        )
        structlog.contextvars.clear_contextvars()
        return

    now = datetime.now(timezone.utc)
    job.status = "completed"
    job.provider = provider
    job.model_name = model
    job.completed_at = now
    job.updated_at = now
    await job.save()
    await audit_service.record(
        "AI Fix Proposals Generated",
        project_id=job.project_id,
        target_type="remediation_job",
        target_id=str(job.id),
        metadata={"scan_id": job.scan_id, "findings": len(findings), "fixable": fixable},
    )
    structlog.contextvars.clear_contextvars()

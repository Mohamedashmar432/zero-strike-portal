"""Map a parsed Go scanner report into portal Finding/Report documents.

Consumed by both the scanner upload endpoint and the server-side cloud scan
service — the single place the Go PascalCase report becomes portal data.
"""

from datetime import datetime, timezone

from app.models.finding import (
    ConfigEmbedded,
    DependencyEmbedded,
    EvidenceEmbedded,
    Finding,
    LocationEmbedded,
    SecretEmbedded,
    TaintContextEmbedded,
)
from app.models.report import DiagnosticEmbedded, Report, ScanStatsEmbedded
from app.models.scan import Scan
from app.schemas.report import (
    GoDiagnosticIn,
    GoFindingIn,
    GoLocationIn,
    GoReportIn,
    GoStatsIn,
)

_SEVERITIES = {"critical", "high", "medium", "low", "info"}
_KINDS = {"sast", "secret", "sca", "config"}


def _location(loc: GoLocationIn) -> LocationEmbedded:
    return LocationEmbedded(
        file=loc.file or "",
        start_line=loc.start_line,
        end_line=loc.end_line,
        start_col=loc.start_col,
        end_col=loc.end_col,
    )


def _map_finding(scan_id: str, project_id: str, f: GoFindingIn) -> Finding:
    return Finding(
        scan_id=scan_id,
        project_id=project_id,
        finding_id=f.finding_id,
        fingerprint=f.fingerprint,
        rule_id=f.rule_id,
        rule_name=f.rule_name,
        category=f.category,
        severity=f.severity if f.severity in _SEVERITIES else None,
        confidence=f.confidence,
        message=f.message or f.rule_name or "(no message)",
        location=_location(f.location),
        language=f.language or None,
        evidence=[
            EvidenceEmbedded(snippet=e.snippet, start_line=e.start_line, end_line=e.end_line)
            for e in f.evidence
        ],
        cwe=f.cwe,
        owasp=f.owasp,
        references=f.references,
        metadata=f.metadata,
        kind=f.kind if f.kind in _KINDS else None,
        secret=(
            SecretEmbedded(detector_id=f.secret.detector_id, entropy=f.secret.entropy, redacted=f.secret.redacted)
            if f.secret
            else None
        ),
        dependency=(
            DependencyEmbedded(
                ecosystem=f.dependency.ecosystem,
                package=f.dependency.package,
                installed_version=f.dependency.installed_version,
                vulnerable_range=f.dependency.vulnerable_range,
                fixed_version=f.dependency.fixed_version,
                advisory_ids=f.dependency.advisory_ids,
                manifest=f.dependency.manifest,
                direct=f.dependency.direct,
            )
            if f.dependency
            else None
        ),
        config=(
            ConfigEmbedded(framework=f.config.framework, config_file=f.config.config_file, key=f.config.key)
            if f.config
            else None
        ),
        rationale=f.rationale,
        remediation=f.remediation,
        taint_context=(
            TaintContextEmbedded(
                source_var=f.taint_context.source_var,
                source_expr=f.taint_context.source_expr,
                sink=f.taint_context.sink,
                path=[_location(p) for p in f.taint_context.path],
            )
            if f.taint_context
            else None
        ),
    )


def _stats(s: GoStatsIn) -> ScanStatsEmbedded:
    return ScanStatsEmbedded(
        files_scanned=s.files_scanned,
        files_skipped=s.files_skipped,
        files_cached=s.files_cached,
        total_findings=s.total_findings,
        suppressed=s.suppressed,
        by_severity=s.by_severity,
        by_language=s.by_language,
        by_category=s.by_category,
        by_kind=s.by_kind,
    )


def _diagnostic(d: GoDiagnosticIn) -> DiagnosticEmbedded:
    return DiagnosticEmbedded(
        severity=d.severity,
        message=d.message,
        location=d.location.file if d.location else None,
    )


async def ingest(scan: Scan, report: GoReportIn, json_path: str) -> int:
    """Write findings + report for `scan` from a parsed Go report, mark the scan completed.

    Idempotent: any prior Finding/Report docs for this scan are replaced (supports re-upload).
    Returns the number of findings ingested. The caller is responsible for the raw artifact file.
    """
    scan_id = str(scan.id)
    project_id = scan.project_id

    await Finding.find(Finding.scan_id == scan_id).delete()
    await Report.find(Report.scan_id == scan_id).delete()

    findings = [_map_finding(scan_id, project_id, f) for f in report.findings]
    if findings:
        await Finding.insert_many(findings)

    now = datetime.now(timezone.utc)
    duration_ms = round(report.duration_ns / 1_000_000) if report.duration_ns is not None else None
    await Report(
        scan_id=scan_id,
        project_id=project_id,
        scanner_scan_id=report.scanner_scan_id,
        scanner_version=report.scanner_version,
        started_at=report.started_at,
        duration_ms=duration_ms,
        root_path=report.root_path,
        git_commit=report.git_commit,
        branch=report.branch,
        hostname=report.hostname,
        stats=_stats(report.stats),
        diagnostics=[_diagnostic(d) for d in report.diagnostics],
        json_path=json_path,
        json_uploaded_at=now,
    ).insert()

    scan.scanner_version = report.scanner_version or scan.scanner_version
    scan.git_commit = report.git_commit or scan.git_commit
    scan.branch = report.branch or scan.branch
    scan.hostname = report.hostname or scan.hostname
    if scan.started_at is None:
        scan.started_at = report.started_at or now
    scan.status = "completed"
    scan.completed_at = now
    scan.updated_at = now
    await scan.save()

    return len(findings)

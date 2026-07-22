"""Map a parsed Go scanner report into portal Finding/Report documents.

Consumed by both the scanner upload endpoint and the server-side cloud scan
service — the single place the Go PascalCase report becomes portal data.
"""

from collections import Counter
from datetime import datetime, timezone

from beanie import PydanticObjectId

from app.core.owasp import OWASP_CODES_ORDERED
from app.core.priority import compute_priority
from app.models.finding import (
    ConfigEmbedded,
    DependencyEmbedded,
    EvidenceEmbedded,
    Finding,
    LocationEmbedded,
    SecretEmbedded,
    TaintContextEmbedded,
)
from app.models.project import Project
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


def normalize_finding_path(file: str, root_path: str | None) -> str:
    """Strip the scan's absolute root/clone-workdir prefix so `file` is repo-relative.

    Cloud scans invoke the scanner with an absolute temp clone dir as its root-path
    argument, and the scanner echoes that same prefix back verbatim in every finding's
    file path (it does no relativizing of its own) — `root_path` here is that identical
    string, taken straight from the report's own RootPath field, so a plain prefix-strip
    is reliable with no cross-OS path-library handling needed. CLI/CI-uploaded reports
    usually pass an already-relative root (e.g. "."), which this leaves untouched.
    """
    if not file or not root_path:
        return file
    norm_file = file.replace("\\", "/")
    norm_root = root_path.replace("\\", "/").rstrip("/")
    if norm_file == norm_root:
        return ""
    if norm_file.startswith(norm_root + "/"):
        return norm_file[len(norm_root) + 1 :]
    return file


def _location(loc: GoLocationIn, root_path: str | None = None) -> LocationEmbedded:
    return LocationEmbedded(
        file=normalize_finding_path(loc.file or "", root_path),
        start_line=loc.start_line,
        end_line=loc.end_line,
        start_col=loc.start_col,
        end_col=loc.end_col,
    )


def _map_finding(
    scan_id: str,
    project_id: str,
    f: GoFindingIn,
    project_repo_id: str | None = None,
    root_path: str | None = None,
) -> Finding:
    severity = f.severity if f.severity in _SEVERITIES else None
    priority_score, priority_tier = compute_priority(severity, f.owasp, f.confidence)
    return Finding(
        scan_id=scan_id,
        project_id=project_id,
        project_repo_id=project_repo_id,
        finding_id=f.finding_id,
        fingerprint=f.fingerprint,
        rule_id=f.rule_id,
        rule_name=f.rule_name,
        category=f.category,
        severity=severity,
        confidence=f.confidence,
        priority_score=priority_score,
        priority_tier=priority_tier,
        message=f.message or f.rule_name or "(no message)",
        location=_location(f.location, root_path),
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
                path=[_location(p, root_path) for p in f.taint_context.path],
            )
            if f.taint_context
            else None
        ),
    )


def _stats(s: GoStatsIn, findings: list[Finding] | None = None) -> ScanStatsEmbedded:
    by_owasp = dict.fromkeys(OWASP_CODES_ORDERED, 0)
    for finding in findings or []:
        for code in finding.owasp:
            if code in by_owasp:
                by_owasp[code] += 1
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
        by_owasp=by_owasp,
    )


def _diagnostic(d: GoDiagnosticIn) -> DiagnosticEmbedded:
    return DiagnosticEmbedded(
        severity=d.severity,
        message=d.message,
        location=d.location.file if d.location else None,
    )


async def _scan_finding_counts(scan_id: str) -> tuple[int, dict[str, int]]:
    """(total findings, per-severity counts) for one scan — a single scan_id-indexed $group.
    Only the five real severities land in the dict (null severity counts toward total only),
    matching how project_stats_service reports findings_by_severity."""
    cursor = Finding.get_pymongo_collection().aggregate(
        [
            {"$match": {"scan_id": scan_id}},
            {"$group": {"_id": "$severity", "count": {"$sum": 1}}},
        ]
    )
    total = 0
    by_severity: dict[str, int] = {}
    for g in await cursor.to_list(length=None):
        total += g["count"]
        if g["_id"] in _SEVERITIES:
            by_severity[g["_id"]] = g["count"]
    return total, by_severity


async def _apply_finding_delta(
    project_id: str, old_total: int, old_by_sev: dict[str, int], findings: list[Finding]
) -> None:
    """$inc the project's denormalized findings rollup by (new - old) for this scan. Single
    mutation point for the counters — keeps them exact across rescans without a full recompute."""
    new_total = len(findings)
    new_by_sev = Counter(f.severity for f in findings if f.severity in _SEVERITIES)
    inc: dict[str, int] = {}
    if new_total != old_total:
        inc["total_findings"] = new_total - old_total
    for sev in _SEVERITIES:
        delta = new_by_sev.get(sev, 0) - old_by_sev.get(sev, 0)
        if delta:
            inc[f"finding_severity_counts.{sev}"] = delta
    if not inc:
        return
    try:
        oid = PydanticObjectId(project_id)
    except Exception:
        return  # non-ObjectId project_id (e.g. a synthetic test scan) — no Project doc to update
    await Project.get_pymongo_collection().update_one({"_id": oid}, {"$inc": inc})


async def ingest(scan: Scan, report: GoReportIn, raw_json: str) -> int:
    """Write findings + report for `scan` from a parsed Go report, mark the scan completed.

    The raw report JSON is stored on the Report doc in Mongo (no filesystem artifacts).
    Idempotent: any prior Finding/Report docs for this scan are replaced (supports re-upload).
    Returns the number of findings ingested.
    """
    scan_id = str(scan.id)
    project_id = scan.project_id

    # Capture the outgoing scan's counts before deleting so the project rollup moves by delta,
    # not by overwrite (a rescan with fewer findings must decrement).
    old_total, old_by_sev = await _scan_finding_counts(scan_id)

    await Finding.find(Finding.scan_id == scan_id).delete()
    await Report.find(Report.scan_id == scan_id).delete()

    findings = [
        _map_finding(scan_id, project_id, f, scan.project_repo_id, report.root_path)
        for f in report.findings
    ]
    if findings:
        await Finding.insert_many(findings)

    await _apply_finding_delta(project_id, old_total, old_by_sev, findings)

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
        stats=_stats(report.stats, findings),
        diagnostics=[_diagnostic(d) for d in report.diagnostics],
        raw_json=raw_json,
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

    # Completion frees a cloud-scan concurrency slot — harmless no-op for local/CI scans.
    from app.services import scan_queue_service

    await scan_queue_service.drain_queue()

    return len(findings)

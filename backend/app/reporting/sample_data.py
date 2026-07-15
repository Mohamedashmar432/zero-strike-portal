"""Hand-built sample Scan/Report/Finding data — powers the report-template preview
endpoint (GET /report-templates/{template}/preview), which isn't scoped to any real
project. Deliberately fake, obviously-labeled data — never a real project's findings.
"""

from datetime import datetime, timezone

from app.core.priority import compute_priority
from app.models.finding import EvidenceEmbedded, Finding, LocationEmbedded
from app.models.report import Report, ScanStatsEmbedded
from app.models.scan import Scan

_SAMPLE_AT = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
_SAMPLE_SCAN_ID = "000000000000000000000001"
_SAMPLE_REPORT_ID = "000000000000000000000002"

_SAMPLE_FINDINGS_RAW = [
    dict(
        rule_id="SAMPLE-001", rule_name="SQL Injection", severity="critical", confidence="high",
        kind="sast", message="Untrusted input flows into a SQL query.", file="app/db.py", line=42,
        owasp=["A03:2025"], cwe=["CWE-89"],
        snippet='cursor.execute("SELECT * FROM users WHERE id = " + id)',
        remediation="Use parameterized queries.",
    ),
    dict(
        rule_id="SAMPLE-002", rule_name="AWS Access Key", severity="high", confidence="high",
        kind="secret", message="AWS access key ID detected in a config file.", file="config/.env",
        line=3, owasp=[], cwe=["CWE-798"], snippet=None,
        remediation="Rotate the key and load it from a secret manager.",
    ),
    dict(
        rule_id="SAMPLE-003", rule_name="Vulnerable Dependency", severity="medium", confidence="high",
        kind="sca", message="A dependency has a known vulnerability.", file="package-lock.json",
        line=None, owasp=["A06:2025"], cwe=["CWE-1321"], snippet=None,
        remediation="Upgrade to the patched version.",
    ),
    dict(
        rule_id="SAMPLE-004", rule_name="Debug Mode Enabled", severity="low", confidence="medium",
        kind="config", message="Debug mode is enabled and may leak sensitive data in production.",
        file="settings.py", line=12, owasp=["A05:2025"], cwe=["CWE-489"], snippet="DEBUG = True",
        remediation="Set DEBUG = False in production settings.",
    ),
    dict(
        rule_id="SAMPLE-005", rule_name="Outdated TLS Version", severity="info", confidence="low",
        kind="config", message="Server accepts TLS 1.0 connections.", file="nginx.conf", line=8,
        owasp=[], cwe=[], snippet=None, remediation="Disable TLS versions below 1.2.",
    ),
]


def _sample_finding(raw: dict) -> Finding:
    priority_score, priority_tier = compute_priority(raw["severity"], raw["owasp"], raw["confidence"])
    return Finding(
        scan_id=_SAMPLE_SCAN_ID,
        project_id="sample",
        rule_id=raw["rule_id"],
        rule_name=raw["rule_name"],
        severity=raw["severity"],
        confidence=raw["confidence"],
        kind=raw["kind"],
        message=raw["message"],
        location=LocationEmbedded(file=raw["file"], start_line=raw["line"]),
        evidence=[EvidenceEmbedded(snippet=raw["snippet"])] if raw["snippet"] else [],
        owasp=raw["owasp"],
        cwe=raw["cwe"],
        remediation=raw["remediation"],
        priority_score=priority_score,
        priority_tier=priority_tier,
        created_at=_SAMPLE_AT,
    )


def build_sample_report() -> tuple[Scan, Report, list[Finding]]:
    """A fixed, obviously-fake dataset — never a real project's findings.

    ``scan_label`` deliberately embeds "Sample Project" (not just "Sample Scan") because
    the standard Jinja template renders ``scan.scan_label`` in its subtitle but never
    receives the ``project_name`` context var (that's executive-template-only in
    pdf_report_service.render_scan_report_html) — this is the only field the standard
    template surfaces that can carry a project-identifying label for the preview.
    """
    scan = Scan(
        id=_SAMPLE_SCAN_ID,
        project_id="sample",
        scan_type="cloud",
        status="completed",
        scan_label="Sample Project — Sample Scan",
        repo_url="https://github.com/sample-org/sample-repo",
        branch="main",
        scanner_version="v0.1.0-sample",
        git_commit="abc123def456abc123def456abc123def456abc",
        hostname="sample-runner",
        started_at=_SAMPLE_AT,
        completed_at=_SAMPLE_AT,
        created_at=_SAMPLE_AT,
        updated_at=_SAMPLE_AT,
    )
    findings = [_sample_finding(raw) for raw in _SAMPLE_FINDINGS_RAW]
    by_severity: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    report = Report(
        id=_SAMPLE_REPORT_ID,
        scan_id=_SAMPLE_SCAN_ID,
        project_id="sample",
        scanner_version="v0.1.0-sample",
        started_at=_SAMPLE_AT,
        duration_ms=8400,
        branch="main",
        git_commit="abc123def456abc123def456abc123def456abc",
        hostname="sample-runner",
        stats=ScanStatsEmbedded(
            files_scanned=37,
            total_findings=len(findings),
            by_severity=by_severity,
            by_kind=by_kind,
        ),
        json_uploaded_at=_SAMPLE_AT,
        generated_at=_SAMPLE_AT,
    )
    return scan, report, findings

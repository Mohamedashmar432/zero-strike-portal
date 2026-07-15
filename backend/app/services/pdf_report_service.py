"""Renders a completed scan's report + findings to PDF.

Two templates: "standard" (scan_report.html.j2, the original plain layout) and
"executive" (scan_report_executive.html.j2, ported from zero-strike-cli's branded
report). See docs/superpowers/specs/2026-07-15-priority-scoring-and-report-templates-design.md.

xhtml2pdf (not WeasyPrint) is the renderer: it's pure Python with no native
Pango/GObject runtime to install, so the same code works unmodified in the Linux
Docker image and on a bare Windows dev machine.
"""

import asyncio
import io
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from xhtml2pdf import pisa

from app.core.owasp import OWASP_TOP_10
from app.models.finding import Finding
from app.models.report import Report
from app.models.scan import Scan

ReportTemplate = Literal["standard", "executive"]

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_MAX_FINDINGS = 2000
_TEMPLATE_FILES: dict[ReportTemplate, str] = {
    "standard": "scan_report.html.j2",
    "executive": "scan_report_executive.html.j2",
}
_KIND_LABELS = {
    "sast": "Static Analysis (SAST)",
    "secret": "Secrets",
    "sca": "Dependencies (SCA)",
    "config": "Configuration",
}

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "reporting" / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _severity_sort_key(finding: Finding) -> tuple[int, str]:
    return (_SEVERITY_ORDER.get(finding.severity, len(_SEVERITY_ORDER)), finding.rule_id or "")


def _overall_risk(by_severity: dict[str, int]) -> str:
    if by_severity.get("critical"):
        return "CRITICAL"
    if by_severity.get("high"):
        return "HIGH"
    if by_severity.get("medium"):
        return "MEDIUM"
    if by_severity.get("low"):
        return "LOW"
    return "NONE"


def _scanners_used(by_kind: dict[str, int]) -> list[str]:
    return [_KIND_LABELS[kind] for kind in ("sast", "secret", "sca", "config") if by_kind.get(kind)]


def _executive_summary(report: Report, total_findings: int) -> str:
    critical = report.stats.by_severity.get("critical", 0)
    files = report.stats.files_scanned
    files_part = f" across {files} file{'s' if files != 1 else ''}" if files is not None else ""
    critical_part = f", {critical} critical" if critical else ""
    return f"{total_findings} finding{'s' if total_findings != 1 else ''}{files_part}{critical_part}."


_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _cwe_summary(findings: list[Finding]) -> list[dict]:
    by_cwe: dict[str, list[Finding]] = {}
    for f in findings:
        for cwe in f.cwe:
            by_cwe.setdefault(cwe, []).append(f)
    summary = []
    for cwe, items in by_cwe.items():
        max_severity = min(items, key=lambda f: _SEVERITY_RANK.get(f.severity, 5)).severity
        summary.append({"cwe": cwe, "count": len(items), "max_severity": max_severity})
    return summary


def _by_priority_desc(findings: list[Finding]) -> list[Finding]:
    # Jinja's `sort(attribute=...)` has no None-safe key option, and `priority_score` is
    # None for findings ingested before this field existed (see Finding model) — sorting
    # a mix of None/float in Jinja raises TypeError, so this is done in Python instead.
    return sorted(findings, key=lambda f: f.priority_score if f.priority_score is not None else -1.0, reverse=True)


def render_scan_report_html(
    scan: Scan,
    report: Report,
    findings: list[Finding],
    template: ReportTemplate = "standard",
    project_name: str | None = None,
) -> str:
    ordered = sorted(findings, key=_severity_sort_key)
    limited = ordered[:_MAX_FINDINGS]
    jinja_template = _env.get_template(_TEMPLATE_FILES[template])
    context: dict = {
        "scan": scan,
        "report": report,
        "findings": limited,
        "total_findings": len(findings),
        "truncated": len(findings) > _MAX_FINDINGS,
    }
    if template == "executive":
        context.update(
            project_name=project_name or "—",
            owasp_all=list(OWASP_TOP_10.items()),
            overall_risk=_overall_risk(report.stats.by_severity),
            scanners_used=_scanners_used(report.stats.by_kind),
            executive_summary=_executive_summary(report, len(findings)),
            cwe_summary=_cwe_summary(findings),
            remediation_findings=_by_priority_desc(findings),
        )
    return jinja_template.render(**context)


def _html_to_pdf_sync(html: str) -> bytes:
    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf)
    if result.err:
        raise RuntimeError(f"PDF rendering failed ({result.err} error(s))")
    return buf.getvalue()


async def render_scan_report_pdf(
    scan: Scan,
    report: Report,
    findings: list[Finding],
    template: ReportTemplate = "standard",
    project_name: str | None = None,
) -> bytes:
    html = render_scan_report_html(scan, report, findings, template, project_name)
    return await asyncio.to_thread(_html_to_pdf_sync, html)

"""Renders a completed scan's report + findings to PDF.

Ports the mechanical (non-AI) half of zero-strike-cli's report renderer: this repo's
own Finding/Report documents already carry every field that tool's AI-enrichment pass
adds on top of raw scanner output (cwe/owasp/remediation are native scanner fields
here, not AI-generated) — nothing needs to be invented, and nothing AI-only (an
executive-summary paragraph, a risk-score-sorted remediation plan) exists to strip.

xhtml2pdf (not WeasyPrint) is the renderer: it's pure Python with no native
Pango/GObject runtime to install, so the same code works unmodified in the Linux
Docker image and on a bare Windows dev machine.
"""

import asyncio
import io
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from xhtml2pdf import pisa

from app.models.finding import Finding
from app.models.report import Report
from app.models.scan import Scan

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_MAX_FINDINGS = 2000

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "reporting" / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _severity_sort_key(finding: Finding) -> tuple[int, str]:
    return (_SEVERITY_ORDER.get(finding.severity, len(_SEVERITY_ORDER)), finding.rule_id or "")


def _render_html(scan: Scan, report: Report, findings: list[Finding]) -> str:
    ordered = sorted(findings, key=_severity_sort_key)
    template = _env.get_template("scan_report.html.j2")
    return template.render(
        scan=scan,
        report=report,
        findings=ordered[:_MAX_FINDINGS],
        total_findings=len(findings),
        truncated=len(findings) > _MAX_FINDINGS,
    )


def _html_to_pdf_sync(html: str) -> bytes:
    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf)
    if result.err:
        raise RuntimeError(f"PDF rendering failed ({result.err} error(s))")
    return buf.getvalue()


async def render_scan_report_pdf(scan: Scan, report: Report, findings: list[Finding]) -> bytes:
    html = _render_html(scan, report, findings)
    return await asyncio.to_thread(_html_to_pdf_sync, html)

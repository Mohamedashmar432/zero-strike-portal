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
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

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

# Templates are written for xhtml2pdf's CSS subset, not a browser: no flex/grid/
# gradients/rgba, and a div's border/background is copied onto every child block,
# so cards are single bordered elements or tables. Long paths/URLs/snippets wrap via
# the `.wrap` class (`-pdf-word-wrap: CJK`, break anywhere) — xhtml2pdf ignores
# word-break/overflow-wrap, and a zero-width space neither breaks nor has a glyph in
# the built-in Helvetica (it rendered as a black box).
_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "reporting" / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)

# A code block that wraps AND must split across pages crashes xhtml2pdf: reportlab raises a
# layout error, then builds its message through xhtml2pdf's buggy `getPlainText` and the real
# error surfaces as "TypeError: sequence item 0: expected str instance, list found" — a 500 on
# the PDF download. Observed with a 400-line snippet, a 2000-char line, or 60 lines x 120 chars.
# 100 columns is about one page-width of 8pt Courier, so capped lines never wrap; ASCII "..."
# because the built-in fonts have no ellipsis glyph in every encoding.
_SNIPPET_MAX_LINES = 40
_SNIPPET_MAX_COLS = 100


def _snippet(text: str | None) -> str:
    # The built-in Courier covers Windows-1252 only: emoji, arrows, a BOM etc. would print as black
    # boxes and log one xhtml2pdf warning per glyph, so unencodable characters become "?".
    text = (text or "").encode("cp1252", "replace").decode("cp1252")
    lines = textwrap.dedent(text).strip("\n").splitlines()
    shown = [ln if len(ln) <= _SNIPPET_MAX_COLS else ln[: _SNIPPET_MAX_COLS - 3] + "..." for ln in lines[:_SNIPPET_MAX_LINES]]
    if len(lines) > _SNIPPET_MAX_LINES:
        shown.append(f"... ({len(lines) - _SNIPPET_MAX_LINES} more lines not shown)")
    return "\n".join(shown)


_env.filters["snippet"] = _snippet


def repo_identity(source: str | None) -> tuple[str, str | None]:
    """(name, owner) for a clone URL, an scp-style remote or a local path — what a report should say
    instead of a raw URL. Mirrors `repoIdentity` in frontend/lib/repo-identity.ts.

    https://dev.azure.com/acme/Platform/_git/Visitor%20management -> ("Visitor management", "acme / Platform")
    https://github.com/octocat/hello-world.git                    -> ("hello-world", "octocat")
    """
    raw = (source or "").strip()
    if not raw:
        return "-", None
    if "://" in raw:
        raw = urlsplit(raw).path  # drops credentials, query and fragment with the host
    elif re.match(r"^[\w.-]+@[\w.-]+:", raw):
        raw = raw.split(":", 1)[1]
    parts = [unquote(p) for p in re.split(r"[\\/]", raw) if p]
    if not parts:
        return (source or "").strip() or "-", None
    git = parts.index("_git") if "_git" in parts else -1
    if git >= 0 and git + 1 < len(parts):
        name, owner_parts = parts[git + 1], parts[:git]
    else:
        name, owner_parts = parts[-1], parts[:-1]
    name = re.sub(r"\.git$", "", name, flags=re.IGNORECASE) or (source or "").strip()
    return name, (" / ".join(owner_parts) or None)


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
    repo_name, repo_owner = repo_identity(scan.repo_url or report.root_path)
    context: dict = {
        "repo_name": repo_name,
        "repo_owner": repo_owner,
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


_FILENAME_UNSAFE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    return _FILENAME_UNSAFE.sub("-", value.lower()).strip("-") or "unknown"


def _repo_name(scan: Scan, report: Report) -> str:
    source = scan.repo_url or report.root_path
    if not source:
        return "unknown-repo"
    # Same naming as the report body (repo_identity): it URL-decodes, so an Azure DevOps repo called
    # "Visitor management" is "visitor-management" here, not "visitor-20management" from its %20.
    return _slugify(repo_identity(source)[0])


def build_report_filename(scan: Scan, report: Report, project_name: str) -> str:
    """"{project}-{repo}-{date}.pdf" — the name users see when they download a report."""
    date = (scan.started_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    return f"{_slugify(project_name)}-{_repo_name(scan, report)}-{date}.pdf"

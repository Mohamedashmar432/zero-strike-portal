"""Outbound alerts: a Teams-compatible webhook and up to three mailboxes per project, plus one
portal-wide webhook for admin events.

Same contract as notification_service: alerting must never break what is being alerted about, so
every public entry point swallows and logs its own failures. The webhook URL is a bearer secret
(Teams puts the token in the path): it is encrypted at rest, only its host is ever shown, and a
send logs the host, never the URL.

What each channel carries: the webhook only ever carries a *link* to the scan (opening it requires a
signed-in project member), while the email — at most three addresses the project owner chose —
carries the PDF report. Every delivery attempt writes one audit row naming the project.
"""

import asyncio
from urllib.parse import urlparse

import httpx
import structlog

from app.core.config import settings
from app.core.repo_url import resolve_vetted_ips
from app.core.security import decrypt_secret
from app.models.finding import NOT_SUPPRESSED, Finding
from app.models.project import Project
from app.models.report import Report
from app.models.scan import Scan
from app.services import (
    audit_service,
    email_service,
    pdf_report_service,
    report_template_service,
    workspace_settings_service,
)

logger = structlog.get_logger(__name__)

_in_flight: set[asyncio.Task] = set()


def vet_webhook_url(url: str) -> str:
    """Return the URL if it is https to a globally routable host, else raise ValueError.

    ponytail: vets DNS at save and at send but does not pin the IP, so a rebinding DNS server could
    answer differently between check and connect. Pin via a custom transport if that ever matters.
    """
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Webhook URL must be an https URL")
    if parsed.username or parsed.password:
        raise ValueError("Webhook URL must not contain credentials")
    resolve_vetted_ips(parsed.hostname)
    return url


def host_of(encrypted: str | None) -> str | None:
    if not encrypted:
        return None
    try:
        return urlparse(decrypt_secret(encrypted)).hostname
    except Exception:
        return None


async def post_webhook(
    url: str, title: str, text: str, link: str | None = None, facts: list[tuple[str, str]] | None = None
) -> None:
    """Adaptive-card message — accepted by Teams Workflows webhooks. `facts` render as a label/value table."""
    await asyncio.to_thread(vet_webhook_url, url)
    content: dict = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": [
            {"type": "TextBlock", "text": title, "weight": "Bolder", "size": "Medium", "wrap": True},
            {"type": "TextBlock", "text": text, "wrap": True},
        ],
    }
    if facts:
        content["body"].append({"type": "FactSet", "facts": [{"title": k, "value": v} for k, v in facts]})
    if link:
        link = _absolute(link)
        content["actions"] = [{"type": "Action.OpenUrl", "title": "Open report in thinkShield", "url": link}]
    payload = {
        "type": "message",
        "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": content}],
    }
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        resp = await client.post(url, json=payload)
    resp.raise_for_status()


def _absolute(link: str) -> str:
    return f"{settings.frontend_origin}{link}" if link.startswith("/") else link


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)


async def _audit(action: str, project_id: str | None, metadata: dict) -> None:
    """One audit row per delivery attempt. System actor (no person did this), project-scoped, and
    never carrying the webhook URL or an address — only the channel, trigger and counts."""
    try:
        await audit_service.record(
            action, actor_type="system", project_id=project_id, target_type="alert", metadata=metadata
        )
    except Exception:
        logger.exception("alert audit failed", project_id=project_id)


async def _safe_webhook(
    encrypted: str,
    title: str,
    text: str,
    link: str | None,
    project_id: str | None,
    meta: dict,
    facts: list[tuple[str, str]] | None = None,
) -> None:
    outcome = "delivered"
    try:
        await post_webhook(decrypt_secret(encrypted), title, text, link, facts)
    except Exception as exc:
        outcome = f"failed: {type(exc).__name__}"
        logger.warning("alert webhook failed", host=host_of(encrypted), error=type(exc).__name__)
    # "delivered" means the endpoint answered 2xx; a retired Teams connector can still drop the card.
    await _audit(
        "Alert Sent" if outcome == "delivered" else "Alert Failed",
        project_id,
        {**meta, "channel": "webhook", "outcome": outcome},
    )


async def _render_pdf(scan_id: str) -> tuple[str, bytes] | None:
    """The same PDF the report download serves, or None when it cannot be built."""
    try:
        scan = await Scan.get(scan_id)
        report = await Report.find_one(Report.scan_id == scan_id)
        project = await Project.get(scan.project_id) if scan else None
        if not (scan and report and project):
            return None
        template = await report_template_service.get_effective_template(project)
        findings = await Finding.find(Finding.scan_id == scan_id, NOT_SUPPRESSED).to_list()
        data = await pdf_report_service.render_scan_report_pdf(scan, report, findings, template, project.name)
        return pdf_report_service.build_report_filename(scan, report, project.name), data
    except Exception:
        logger.exception("alert pdf render failed", scan_id=scan_id)
        return None


async def _safe_emails(
    addresses: list[str], title: str, text: str, link: str | None, project_id: str, meta: dict, scan_id: str | None
) -> None:
    pdf = await _render_pdf(scan_id) if scan_id else None

    def _send() -> int:
        body = f"{text}\n\n{_absolute(link)}" if link else text
        if scan_id and pdf is None:
            body += "\n\n(The PDF report could not be attached; open the link above to view it.)"
        failed = 0
        for address in addresses:
            try:
                email_service.send_email(address, f"[thinkShield] {title}", body, attachments=[pdf] if pdf else None)
            except Exception:
                failed += 1
                logger.warning("alert email failed", exc_info=True)
        return failed

    failed = len(addresses)
    try:
        failed = await asyncio.to_thread(_send)
    except Exception:
        logger.exception("alert email batch failed")
    await _audit(
        "Alert Sent" if failed < len(addresses) else "Alert Failed",
        project_id,
        {**meta, "channel": "email", "recipients": len(addresses), "failed": failed, "pdf_attached": pdf is not None},
    )


async def send_project_alert(
    project: Project,
    trigger: str,
    title: str,
    text: str,
    link: str | None,
    scan_id: str | None = None,
    facts: list[tuple[str, str]] | None = None,
) -> None:
    """Fire on this project's channels if `trigger` and the channel are switched on. With a
    `scan_id` the email carries that scan's PDF; the webhook only ever carries the link."""
    if trigger not in project.alert_triggers:
        return
    project_id = str(project.id)
    meta = {"trigger": trigger, "scan_id": scan_id, "project": project.name}
    if project.alert_webhook_enabled and project.alert_webhook_enc:
        _spawn(_safe_webhook(project.alert_webhook_enc, title, text, link, project_id, meta, facts))
    if project.alert_email_enabled and project.alert_emails:
        _spawn(_safe_emails(list(project.alert_emails), title, text, link, project_id, meta, scan_id))


async def on_scan_completed(scan, findings: list, link: str) -> None:
    """Critical / high / vulnerable-package alert for a finished scan. Never raises."""
    project_id, scan_id = scan.project_id, str(scan.id)
    try:
        project = await workspace_settings_service.load_project(project_id)
        if project is None:
            return
        live = [f for f in findings if not f.suppressed]
        counts = {
            "critical": sum(f.severity == "critical" for f in live),
            "high": sum(f.severity == "high" for f in live),
            "vulnerable_package": sum(f.kind == "sca" for f in live),
        }
        labels = {
            "critical": "critical finding(s)",
            "high": "high finding(s)",
            "vulnerable_package": "vulnerable package(s)",
        }
        hits = [t for t in labels if counts[t] and t in project.alert_triggers]
        if not hits:
            return
        summary = ", ".join(f"{counts[t]} {labels[t]}" for t in hits)
        sev = {s: sum(f.severity == s for f in live) for s in ("critical", "high", "medium", "low")}
        repo_name, repo_owner = pdf_report_service.repo_identity(scan.repo_url)
        facts = [
            ("Project", project.name),
            ("Repository", f"{repo_owner} / {repo_name}" if repo_owner else repo_name),
            ("Branch", scan.branch or "-"),
            *[(s.capitalize(), str(n)) for s, n in sev.items()],
            ("Vulnerable packages", str(counts["vulnerable_package"])),
        ]
        # The email carries the same facts as plain lines above its PDF.
        text = f"{summary}.\n\n" + "\n".join(f"{k}: {v}" for k, v in facts)
        # One message per scan however many triggers matched; any matched trigger passes the gate.
        # `src=alert` tells the sign-in gate a signed-out visitor came from an alert link.
        await send_project_alert(
            project, hits[0], f"{project.name}: scan found {summary}", text, f"{link}?src=alert", scan_id, facts
        )
    except Exception:
        logger.exception("scan alert failed", project_id=project_id, scan_id=scan_id)


async def on_scan_failed(project_id: str, title: str, text: str, link: str | None) -> None:
    try:
        project = await workspace_settings_service.load_project(project_id)
        if project is not None:
            await send_project_alert(project, "scan_failed", title, text, link)
    except Exception:
        logger.exception("scan-failed alert failed", project_id=project_id)


async def send_global(title: str, text: str, link: str | None = None) -> None:
    """Forward an admin-audience event to the portal-wide webhook. Never raises."""
    try:
        ws = await workspace_settings_service.get_workspace_settings()
        if ws.alert_webhook_enabled and ws.alert_webhook_enc:
            _spawn(_safe_webhook(ws.alert_webhook_enc, title, text, link, None, {"trigger": "admin_event"}))
    except Exception:
        logger.exception("global alert failed")

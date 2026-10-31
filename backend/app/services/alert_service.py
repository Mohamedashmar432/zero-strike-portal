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


def message_card(
    title: str,
    text: str,
    link: str | None = None,
    facts: list[tuple[str, str]] | None = None,
    *,
    tone: str = "accent",
    eyebrow: str | None = None,
) -> dict:
    """The one alert-card layout: a coloured header band (tone = Adaptive Card container style:
    attention / warning / good / accent), the message, its facts, and an open button. Only 1.4
    elements, because legacy Office 365 connector webhooks drop newer ones (e.g. Table) silently."""
    header = [
        {
            "type": "TextBlock",
            "text": f"THINKSHIELD · {eyebrow.upper()}" if eyebrow else "THINKSHIELD",
            "size": "Small",
            "weight": "Bolder",
            "isSubtle": True,
            "wrap": True,
        },
        {"type": "TextBlock", "text": title, "size": "Large", "weight": "Bolder", "wrap": True, "spacing": "None"},
    ]
    body: list[dict] = [{"type": "Container", "style": tone, "bleed": True, "items": header}]
    if text and text != title:
        body.append({"type": "TextBlock", "text": text, "wrap": True, "spacing": "Medium"})
    if facts:
        body.append(
            {
                "type": "Container",
                "separator": True,
                "spacing": "Medium",
                "items": [{"type": "FactSet", "facts": [{"title": k, "value": v or "-"} for k, v in facts]}],
            }
        )
    content: dict = {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "msteams": {"width": "Full"},
        "body": body,
    }
    if link:
        content["actions"] = [{"type": "Action.OpenUrl", "title": "Open in thinkShield", "url": _absolute(link)}]
    return content


async def post_webhook(
    url: str,
    title: str,
    text: str,
    link: str | None = None,
    facts: list[tuple[str, str]] | None = None,
    *,
    tone: str = "accent",
    eyebrow: str | None = None,
) -> int:
    """Adaptive-card message — accepted by Teams Workflows and legacy connector webhooks."""
    return await post_card(url, message_card(title, text, link, facts, tone=tone, eyebrow=eyebrow))


async def post_card(url: str, content: dict) -> int:
    """Post a ready-made Adaptive Card (the digest builds its own, with a Table). Vets the URL first."""
    await asyncio.to_thread(vet_webhook_url, url)
    payload = {
        "type": "message",
        "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": content}],
    }
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        resp = await client.post(url, json=payload)
    resp.raise_for_status()
    return resp.status_code


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
    **style,
) -> str:
    """Returns the outcome ("delivered" or "failed: <ExceptionType>") as well as auditing it."""
    outcome = "delivered"
    try:
        await post_webhook(decrypt_secret(encrypted), title, text, link, facts, **style)
    except Exception as exc:
        outcome = f"failed: {type(exc).__name__}"
        logger.warning("alert webhook failed", host=host_of(encrypted), error=type(exc).__name__)
    # "delivered" means the endpoint answered 2xx; a retired Teams connector can still drop the card.
    await _audit(
        "Alert Sent" if outcome == "delivered" else "Alert Failed",
        project_id,
        {**meta, "channel": "webhook", "outcome": outcome},
    )
    return outcome


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
) -> str:
    """Returns "sent" when at least one address was accepted, else "failed" (same rule as the audit row)."""
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
    return "sent" if failed < len(addresses) else "failed"


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


async def send_project_live_alert(
    project: Project, title: str, text: str, link: str | None, facts: list[tuple[str, str]] | None = None
) -> tuple[str, str]:
    """A live dependency alert on this project's own webhook and mailboxes. Returns (webhook, email)
    outcomes for the delivery record. Bypasses `alert_triggers` (there is no tick-box for it: switching
    the project's alerts to Off is the opt-out), but still needs the channel itself switched on.

    Awaited rather than spawned, so the ledger records what actually happened. Email is never attempted
    while SMTP is unset, and "sent" is only ever returned by a send that was accepted. Never raises."""
    project_id = str(project.id)
    meta = {"trigger": "live_dependency_alert", "project": project.name}
    webhook, email = "off", "off"
    try:
        if project.alert_webhook_enabled and project.alert_webhook_enc:
            outcome = await _safe_webhook(
                project.alert_webhook_enc, title, text, link, project_id, meta, facts,
                tone="attention", eyebrow="New dependency advisory",
            )
            webhook = "sent" if outcome == "delivered" else "failed"
        if project.alert_email_enabled and project.alert_emails:
            if not settings.smtp_host:
                email = "not_configured"
            else:
                lines = "\n".join(f"{k}: {v}" for k, v in facts or [])
                body = f"{text}\n\n{lines}" if lines else text
                email = await _safe_emails(list(project.alert_emails), title, body, link, project_id, meta, None)
    except Exception:
        logger.warning("project live alert failed", project_id=project_id, exc_info=True)
        webhook = "failed" if webhook == "off" and project.alert_webhook_enabled else webhook
    return webhook, email


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
    """Forward an admin-audience event to the portal-wide webhook. Never raises.

    Stands down once the workspace webhook has been migrated to a channel
    (webhook_channel_service): notify() then routes it, and posting here too would double-send."""
    try:
        from app.services import webhook_channel_service

        if await webhook_channel_service.has_migrated_channel():
            return
        ws = await workspace_settings_service.get_workspace_settings()
        if ws.alert_webhook_enabled and ws.alert_webhook_enc:
            _spawn(_safe_webhook(ws.alert_webhook_enc, title, text, link, None, {"trigger": "admin_event"}))
    except Exception:
        logger.exception("global alert failed")

"""Minimal SMTP email sending — stdlib only (smtplib + email), no template engine.

Every email the portal sends goes through `send_email`, which is also the one place the
branded HTML layout is applied, so no sender can ship an unbranded message. Deliberately
synchronous: smtplib is blocking, so a caller running in an async context should
wrap these in `asyncio.to_thread` rather than this module growing an async API.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape

import structlog

from app.core.config import settings
from app.core.email_templates import INK, MONO, MUTED, SIGNAL, to_html

logger = structlog.get_logger(__name__)

_SANS = "Archivo,'Segoe UI',Helvetica,Arial,sans-serif"


def _layout(content: str, subject: str) -> str:
    """Wrap a body fragment in the Signal Room email shell: graphite header with the lime rule,
    warm-paper canvas, hairline card, muted footer. Tables, not divs: Outlook ignores most CSS."""
    origin = settings.frontend_origin
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f2f1ec">
<span style="display:none;max-height:0;overflow:hidden;opacity:0">{escape(subject)}</span>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f1ec">
<tr><td align="center" style="padding:32px 16px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
 style="max-width:560px;background:#fbfbf8;border:1px solid #dcdad1;border-radius:3px">
<tr><td style="background:#131316;border-top:3px solid {SIGNAL};border-radius:3px 3px 0 0;padding:18px 32px">
<span style="display:inline-block;width:8px;height:8px;background:{SIGNAL};margin-right:10px"></span>
<span style="font-family:{MONO};font-size:15px;letter-spacing:.02em;color:#e8e8e2"><b>think</b>Shield</span>
<span style="font-family:{MONO};font-size:11px;letter-spacing:.12em;color:#96968e;margin-left:6px">PORTAL</span>
</td></tr>
<tr><td style="padding:32px;font-family:{_SANS};font-size:15px;line-height:1.6;color:{INK}">
{content}
</td></tr>
<tr><td style="padding:18px 32px;border-top:1px solid #dcdad1;font-family:{_SANS};font-size:12px;line-height:1.5;color:{MUTED}">
Sent by thinkShield Portal. Manage which emails you receive in
<a href="{origin}/settings/notifications" style="color:{MUTED}">notification settings</a>.
</td></tr>
</table>
</td></tr></table>
</body></html>"""


def send_email(to_address: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Send a plaintext + branded HTML email via settings.smtp_*. Without an `html_body`, the
    HTML part is derived from the text, so plain-text senders get the same layout.

    If smtp_host is unset (the dev default, since no SMTP server is configured yet),
    logs a warning and returns without attempting to connect — keeps local/dev usable
    without SMTP configured.
    """
    if not settings.smtp_host:
        logger.warning("SMTP not configured (smtp_host empty) — skipping email")
        return

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address
    message["To"] = to_address
    message.attach(MIMEText(text_body, "plain"))
    content = html_body if html_body is not None else to_html(escape(text_body, quote=False))
    message.attach(MIMEText(_layout(content, subject), "html"))

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username and settings.smtp_password:
            server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(settings.smtp_from_address, [to_address], message.as_string())


def send_password_reset_email(to_address: str, reset_url: str, ttl_minutes: int) -> None:
    """Send the password-reset link email. Single hardcoded template — not worth Jinja2.

    ttl_minutes must reflect the caller's actual token lifetime (settings.password_reset_token_ttl_minutes)
    — the email body quotes it directly, so a mismatch would tell users the wrong expiry.
    """
    subject = "Reset your thinkShield Portal password"
    text_body = (
        "You requested a password reset for your thinkShield Portal account.\n\n"
        f"Reset your password using this link:\n{reset_url}\n\n"
        f"This link expires in {ttl_minutes} minutes. If you did not request this, you can ignore this email."
    )
    send_email(to_address, subject, text_body, to_html(escape(text_body)))

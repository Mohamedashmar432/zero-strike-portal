"""Minimal SMTP email sending — stdlib only (smtplib + email), no template engine.

Used by the forgot-password flow to send a password-reset link. Deliberately
synchronous: smtplib is blocking, so a caller running in an async context should
wrap these in `asyncio.to_thread` rather than this module growing an async API.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


def send_email(to_address: str, subject: str, text_body: str, html_body: str | None = None) -> None:
    """Send a plaintext (+ optional HTML) email via settings.smtp_*.

    If smtp_host is unset (the dev default, since no SMTP server is configured yet),
    logs a warning and returns without attempting to connect — keeps local/dev usable
    without SMTP configured.
    """
    if not settings.smtp_host:
        logger.warning("SMTP not configured (smtp_host empty) — skipping email to %s", to_address)
        return

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = settings.smtp_from_address
    message["To"] = to_address
    message.attach(MIMEText(text_body, "plain"))
    if html_body is not None:
        message.attach(MIMEText(html_body, "html"))

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
    subject = "Reset your ZeroStrike Portal password"
    text_body = (
        "You requested a password reset for your ZeroStrike Portal account.\n\n"
        f"Reset your password using this link:\n{reset_url}\n\n"
        f"This link expires in {ttl_minutes} minutes. If you did not request this, you can ignore this email."
    )
    html_body = (
        "<p>You requested a password reset for your ZeroStrike Portal account.</p>"
        f'<p><a href="{reset_url}">Reset your password</a></p>'
        f"<p>This link expires in {ttl_minutes} minutes. If you did not request this, you can ignore this "
        "email.</p>"
    )
    send_email(to_address, subject, text_body, html_body)

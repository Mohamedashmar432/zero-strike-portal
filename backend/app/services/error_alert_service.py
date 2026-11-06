"""`portal.error`: tell admins when the backend logs an ERROR
(docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md section 9).

Fed by `core.log_sink.flush` with the rows it has just persisted, so there is exactly one source of
truth for "what the backend logged". Grouped by logger + a normalised message (digits and ids
stripped, so "scan 123 failed" and "scan 456 failed" are one problem) and sent once per group per
hour, with an overall cap so a failure storm with many distinct messages cannot flood a channel.

An alert must not alert about itself: records from the modules that deliver alerts are skipped, and
those modules log delivery failures at WARNING, which is below this threshold anyway.
"""

import hashlib
import re

import structlog

from app.core import dedupe
from app.services import notification_service

logger = structlog.get_logger(__name__)

_LEVELS = {"error", "critical"}
_SKIP_LOGGER_PREFIXES = (
    "app.services.webhook_channel_service",
    "app.services.notification_service",
    "app.services.alert_service",
    "app.services.error_alert_service",
    "app.services.digest_service",
)
_WINDOW_SECONDS = 3600
_MAX_ALERTS_PER_WINDOW = 20
_NOISE = re.compile(r"[0-9a-fA-F]{8,}|\d+")


def fingerprint(logger_name: str, message: str) -> str:
    normalised = _NOISE.sub("#", message)[:300]
    return hashlib.sha1(f"{logger_name}|{normalised}".encode(), usedforsecurity=False).hexdigest()[:16]


def _eligible(row: dict) -> bool:
    # main.py's catch-all handler logs every unhandled exception with its request id, then Starlette
    # re-raises and uvicorn logs the same crash: alert on the first, not both.
    if row["logger"].startswith("uvicorn") and row["message"].startswith("Exception in ASGI application"):
        return False
    return row["level"] in _LEVELS and not row["logger"].startswith(_SKIP_LOGGER_PREFIXES)


async def alert_rows(rows: list[dict]) -> int:
    """Send `portal.error` for the first occurrence of each distinct error in `rows`. Never raises."""
    sent = 0
    try:
        for row in rows:
            if not _eligible(row):
                continue
            key = fingerprint(row["logger"], row["message"])
            if not dedupe.alerts.first(
                f"portal.error:{key}", _WINDOW_SECONDS, group="portal.error", group_cap=_MAX_ALERTS_PER_WINDOW
            ):
                continue
            message = row["message"][:300]
            last_line = (row.get("exception") or "").strip().splitlines()[-1:] or [""]
            context = row.get("context") or {}
            facts = [("Logger", row["logger"]), ("Level", row["level"])]
            if context.get("request_id"):
                facts.append(("Request id", str(context["request_id"])))
            if last_line[0]:
                facts.append(("Exception", last_line[0][:300]))
            await notification_service.notify(
                "portal.error",
                title=f"Portal error: {message[:100]}",
                body=message,
                link="/admin/audit-log",
                severity="error",
                facts=facts,
            )
            sent += 1
    except Exception:
        logger.warning("portal error alert failed", exc_info=True)
    return sent

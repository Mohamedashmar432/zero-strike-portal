"""Admin-sent acknowledgement of a project's accepted risks (docs/RISK_ACCEPT_REVIEW_AND_VULN_REDESIGN.md).

Accepting a risk exempts a finding from the CI gate, so someone accountable should be able to see, in
one document, everything the project has accepted. A portal admin sends that document -- never
automatically -- to the project owner plus up to ten extra addresses, as a PDF and a CSV with a link to
acknowledge. The batch is a frozen snapshot (`RiskAcknowledgementBatch.items`); its state is derived on
read, and an acknowledgement stops counting the moment any accepted risk in it is re-decided.

Delivery honesty: with `smtp_host` unset a recipient is recorded `not_configured`, SMTP is never
attempted, and nothing in the API or UI may say "sent" for it. Every state change writes an audit row
that never contains an address.
"""

import asyncio
import csv
import io
import re
from datetime import datetime, timedelta, timezone
from html import escape

import structlog
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.email_templates import to_html
from app.core.security import generate_reset_token, hash_token
from app.core.timeutils import as_utc
from app.models.project import Project
from app.models.risk_acknowledgement import AckItem, AckRecipient, RiskAcknowledgementBatch
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.services import audit_service, email_service, notification_service, pdf_report_service

logger = structlog.get_logger(__name__)

TOKEN_TTL_DAYS = 14
MAX_SENDS_PER_RECIPIENT = 5
RESEND_THROTTLE = timedelta(minutes=10)
MAX_EXTRA_RECIPIENTS = 10
_MAX_MESSAGE_CHARS = 1000
# The request awaits delivery so recorded outcomes are truthful, so an unreachable relay must not hold it
# open: each SMTP socket operation is capped, and all recipients together share one budget.
SMTP_TIMEOUT_SECONDS = 5.0
SEND_BUDGET_SECONDS = 15.0
_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def mask_email(email: str) -> str:
    """"alice@example.com" -> "a***@e***.com". Non-admins see who was asked, not the full address."""
    local, _, domain = email.partition("@")
    host, _, tld = domain.rpartition(".")
    return f"{local[:1]}***@{host[:1]}***.{tld}" if host else f"{local[:1]}***"


def _link(raw_token: str) -> str:
    # The token rides in the fragment: it is never sent to the server in a request line, so it stays out
    # of access logs and Referer headers until the page itself posts it in a request body.
    return f"{settings.frontend_origin.rstrip('/')}/acknowledge-risk#token={raw_token}"


# --- eligible items and the frozen snapshot ----------------------------------------------------------


async def eligible_items(project_id: str) -> list[Vulnerability]:
    """Every finding of the project whose accepted-risk review has been accepted."""
    return await Vulnerability.find(
        {"project_id": project_id, "review.kind": "accepted_risk", "review.status": "accepted"}
    ).sort("-review.reviewed_at").to_list()


async def emails_for(user_ids: set[str]) -> dict[str, str]:
    from beanie import PydanticObjectId
    from beanie.operators import In

    valid = [PydanticObjectId(i) for i in user_ids if i and PydanticObjectId.is_valid(i)]
    if not valid:
        return {}
    return {str(u.id): u.email for u in await User.find(In(User.id, valid)).to_list()}


async def snapshot(vulns: list[Vulnerability]) -> list[AckItem]:
    """The items as they are right now: also what the preview report renders, so preview and sent copy agree."""
    ids: set[str] = set()
    for v in vulns:
        ids.add(v.review.requested_by_user_id)
        if v.review.reviewed_by_user_id:
            ids.add(v.review.reviewed_by_user_id)
    emails = await emails_for(ids)
    return [
        AckItem(
            vulnerability_id=str(v.id),
            fingerprint=v.fingerprint,
            rule_id=v.current_rule_id,
            rule_name=v.current_rule_name,
            severity=v.current_severity,
            kind=v.current_kind,
            file_path=v.review.file_path,
            requested_by_user_id=v.review.requested_by_user_id,
            requested_by_email=emails.get(v.review.requested_by_user_id),
            requested_at=as_utc(v.review.requested_at),
            reviewed_by_user_id=v.review.reviewed_by_user_id,
            reviewed_by_email=emails.get(v.review.reviewed_by_user_id or ""),
            reviewed_at=as_utc(v.review.reviewed_at),
            comment=v.review.request_comment,
            auto_accepted=(v.review.review_comment or "").startswith("Auto-accepted"),
        )
        for v in vulns
    ]


# --- derived state -----------------------------------------------------------------------------------


async def live_reviews(batches: list[RiskAcknowledgementBatch]) -> dict[str, tuple[str | None, datetime | None]]:
    """vulnerability_id -> (review.status, review.reviewed_at) for every item of the given batches."""
    from beanie import PydanticObjectId
    from beanie.operators import In

    oids = [
        PydanticObjectId(i.vulnerability_id)
        for b in batches
        for i in b.items
        if PydanticObjectId.is_valid(i.vulnerability_id)
    ]
    if not oids:
        return {}
    rows = await Vulnerability.find(In(Vulnerability.id, oids)).to_list()
    return {str(v.id): (v.review.status, as_utc(v.review.reviewed_at)) if v.review else (None, None) for v in rows}


def item_is_current(item: AckItem, live: dict[str, tuple[str | None, datetime | None]]) -> bool:
    """An item is covered only while the finding is still accepted by the very decision that was snapshotted."""
    got = live.get(item.vulnerability_id)
    return bool(got) and got[0] == "accepted" and got[1] == as_utc(item.reviewed_at)


def state_for(batch: RiskAcknowledgementBatch, live: dict[str, tuple[str | None, datetime | None]]) -> dict:
    """`acknowledged` | `superseded` (acknowledged, but a covered risk was re-decided or revoked since) |
    `expired` (nobody acknowledged and every link has lapsed) | `pending`."""
    now = datetime.now(timezone.utc)
    current = sum(1 for i in batch.items if item_is_current(i, live))
    acked = [r for r in batch.recipients if r.acknowledged_at]
    if acked:
        state = "acknowledged" if current == len(batch.items) else "superseded"
    elif all(not r.token_expires_at or as_utc(r.token_expires_at) < now for r in batch.recipients):
        state = "expired"
    else:
        state = "pending"
    return {
        "state": state,
        "items_current": current,
        "items_superseded": len(batch.items) - current,
        "recipients_sent": sum(1 for r in batch.recipients if r.delivery == "sent"),
        "recipients_acknowledged": len(acked),
    }


# --- create / send / resend --------------------------------------------------------------------------


def _clean_extras(owner_email: str, extras: list[str]) -> list[str]:
    seen = {owner_email.lower()}
    out: list[str] = []
    for raw in extras:
        e = (raw or "").strip().lower()
        if not e or len(e) > 254 or not _EMAIL_RE.match(e):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "One of the extra recipients is not a valid email address")
        if e not in seen:
            seen.add(e)
            out.append(e)
    if len(out) > MAX_EXTRA_RECIPIENTS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"At most {MAX_EXTRA_RECIPIENTS} extra recipients are allowed"
        )
    return out


def _issue_token(recipient: AckRecipient, now: datetime) -> str:
    raw, hashed = generate_reset_token()
    recipient.token_hash = hashed
    recipient.token_expires_at = now + timedelta(days=TOKEN_TTL_DAYS)
    return raw


async def create_and_send(
    project: Project, admin: User, extra_recipients: list[str], message: str | None
) -> RiskAcknowledgementBatch:
    vulns = await eligible_items(str(project.id))
    if not vulns:
        raise HTTPException(status.HTTP_409_CONFLICT, "This project has no accepted risks to acknowledge")
    owner = await User.get(project.owner_id) if project.owner_id else None
    if owner is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This project has no owner account to send to")
    extras = _clean_extras(owner.email, extra_recipients)
    message = (message or "").strip()[:_MAX_MESSAGE_CHARS] or None

    now = datetime.now(timezone.utc)
    recipients = [AckRecipient(email=owner.email, is_project_owner=True, user_id=str(owner.id))]
    recipients += [AckRecipient(email=e) for e in extras]
    tokens = [_issue_token(r, now) for r in recipients]
    batch = RiskAcknowledgementBatch(
        project_id=str(project.id),
        created_by_user_id=str(admin.id),
        created_at=now,
        message=message,
        items=await snapshot(vulns),
        recipients=recipients,
    )
    # Claim-then-deliver: the batch (with hashed tokens) exists before anything is mailed.
    await batch.insert()
    await audit_service.record(
        "Risk Acknowledgement Requested",
        actor_type="user",
        actor_user_id=str(admin.id),
        project_id=batch.project_id,
        target_type="risk_acknowledgement",
        target_id=str(batch.id),
        metadata={"items": len(batch.items), "recipients": len(recipients), "extra_recipients": len(extras)},
    )
    await notification_service.notify(
        "risk.acknowledgement_requested",
        project_id=batch.project_id,
        title="Risk acknowledgement requested",
        body=f"An admin asked you to acknowledge {len(batch.items)} accepted risk(s) in {project.name}.",
        link=f"/projects/{batch.project_id}/vulnerabilities?view=risk",
        severity="warning",
        only_user_ids=[str(owner.id)],
    )
    await _send_all(batch, project.name, dict(zip(range(len(recipients)), tokens)))
    return batch


async def _send_all(batch: RiskAcknowledgementBatch, project_name: str, tokens: dict[int, str]) -> None:
    """Deliver to the recipients named in `tokens` (index -> raw token), then persist each outcome."""
    attachments = None
    if settings.smtp_host and tokens:
        items = batch.items
        pdf = await pdf_report_service.render_risk_acceptance_pdf(project_name, items, batch.created_at)
        attachments = [
            ("risk-acceptance-report.pdf", pdf),
            ("risk-acceptance-report.csv", render_csv(items)),
        ]
    now = datetime.now(timezone.utc)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SEND_BUDGET_SECONDS
    for idx, raw in tokens.items():
        r = batch.recipients[idx]
        if not settings.smtp_host:
            # Not attempted at all, so never reported as sent.
            r.delivery = "not_configured"
            continue
        remaining = deadline - loop.time()
        if remaining <= 0:
            # Budget spent on earlier recipients: not attempted, so recorded failed (resend retries it).
            r.delivery = "failed"
            continue
        try:
            await asyncio.wait_for(
                asyncio.to_thread(_send_one, r.email, project_name, batch, raw, attachments), remaining
            )
            r.delivery = "sent"
            r.send_count += 1
            r.last_sent_at = now
        except Exception:
            # email_service already logged an SMTP failure (type and code only, never the address); a
            # TimeoutError here means the overall budget ran out. Either way it was not delivered.
            r.delivery = "failed"
    await batch.save()


def _send_one(to: str, project_name: str, batch: RiskAcknowledgementBatch, raw_token: str, attachments) -> None:
    subject = f"Risk acceptance acknowledgement requested: {project_name}"
    text = (
        f"A thinkShield Portal administrator asks you to acknowledge {len(batch.items)} finding(s) in "
        f"{project_name} that were accepted as risk and no longer block CI.\n\n"
        + (f"Message from the administrator:\n{batch.message}\n\n" if batch.message else "")
        + "The attached PDF and CSV list each accepted risk, who accepted it and why.\n\n"
        f"Review and acknowledge:\n{_link(raw_token)}\n\n"
        f"The link works once and expires in {TOKEN_TTL_DAYS} days. If you did not expect this email, "
        "you can ignore it."
    )
    email_service.send_email(
        to, subject, text, to_html(escape(text, quote=False)), attachments=attachments, timeout=SMTP_TIMEOUT_SECONDS
    )


async def resend(batch: RiskAcknowledgementBatch, project: Project, admin: User) -> RiskAcknowledgementBatch:
    """Re-mail every recipient who has not acknowledged, with a fresh link (the old one stops working)."""
    now = datetime.now(timezone.utc)
    waiting = [(i, r) for i, r in enumerate(batch.recipients) if not r.acknowledged_at]
    if not waiting:
        raise HTTPException(status.HTTP_409_CONFLICT, "Every recipient has already acknowledged")
    if any(r.send_count >= MAX_SENDS_PER_RECIPIENT for _, r in waiting):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A recipient has already been sent this request {MAX_SENDS_PER_RECIPIENT} times"
        )
    last = [as_utc(r.last_sent_at) for _, r in waiting if r.last_sent_at]
    if last and now - max(last) < RESEND_THROTTLE:
        wait = int((RESEND_THROTTLE - (now - max(last))).total_seconds() // 60) + 1
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"Sent a moment ago. Try again in about {wait} minute(s)")
    tokens = {i: _issue_token(r, now) for i, r in waiting}
    await batch.save()  # the rotated hashes land before anything is mailed
    await audit_service.record(
        "Risk Acknowledgement Resent",
        actor_type="user",
        actor_user_id=str(admin.id),
        project_id=batch.project_id,
        target_type="risk_acknowledgement",
        target_id=str(batch.id),
        metadata={"recipients": len(tokens)},
    )
    await _send_all(batch, project.name, tokens)
    return batch


# --- acknowledging -----------------------------------------------------------------------------------


async def _find_by_token(raw_token: str) -> tuple[RiskAcknowledgementBatch, AckRecipient] | None:
    """The batch and recipient a live token belongs to, or None -- for an unknown, used or expired token
    alike, so a caller cannot tell the three apart."""
    if not raw_token or len(raw_token) > 256:
        return None
    hashed = hash_token(raw_token)
    batch = await RiskAcknowledgementBatch.find_one({"recipients.token_hash": hashed})
    if batch is None:
        return None
    recipient = next((r for r in batch.recipients if r.token_hash == hashed), None)
    if recipient is None or recipient.acknowledged_at:
        return None
    if not recipient.token_expires_at or as_utc(recipient.token_expires_at) < datetime.now(timezone.utc):
        await audit_service.record(
            "Risk Acknowledgement Link Expired",
            actor_type="anonymous",
            project_id=batch.project_id,
            target_type="risk_acknowledgement",
            target_id=str(batch.id),
        )
        return None
    return batch, recipient


async def lookup_by_token(raw_token: str) -> tuple[RiskAcknowledgementBatch, AckRecipient, str] | None:
    found = await _find_by_token(raw_token)
    if found is None:
        return None
    project = await Project.get(found[0].project_id)
    return found[0], found[1], project.name if project else "Deleted project"


async def acknowledge_by_token(raw_token: str) -> RiskAcknowledgementBatch | None:
    found = await _find_by_token(raw_token)
    if found is None:
        return None
    batch, recipient = found
    # Single use, atomically: the update only matches while this recipient has not acknowledged, and it
    # clears the token, so two concurrent requests cannot both succeed.
    result = await RiskAcknowledgementBatch.get_pymongo_collection().update_one(
        {
            "_id": batch.id,
            "recipients": {"$elemMatch": {"token_hash": recipient.token_hash, "acknowledged_at": None}},
        },
        {
            "$set": {
                "recipients.$.acknowledged_at": datetime.now(timezone.utc),
                "recipients.$.acknowledged_by": recipient.email,
                "recipients.$.acknowledged_via": "link",
                "recipients.$.token_hash": None,
            }
        },
    )
    if result.modified_count != 1:
        return None
    await _record_acknowledged(batch, "link", actor_type="anonymous", actor_user_id=None)
    return await RiskAcknowledgementBatch.get(batch.id)


async def acknowledge_in_portal(batch: RiskAcknowledgementBatch, user: User) -> RiskAcknowledgementBatch:
    """The project owner acknowledges from the portal -- the same record as following the emailed link."""
    owner = next((r for r in batch.recipients if r.is_project_owner), None)
    if owner is None or owner.user_id != str(user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the project owner can acknowledge this request")
    result = await RiskAcknowledgementBatch.get_pymongo_collection().update_one(
        {"_id": batch.id, "recipients": {"$elemMatch": {"is_project_owner": True, "acknowledged_at": None}}},
        {
            "$set": {
                "recipients.$.acknowledged_at": datetime.now(timezone.utc),
                "recipients.$.acknowledged_by": user.email,
                "recipients.$.acknowledged_via": "portal",
                "recipients.$.token_hash": None,
            }
        },
    )
    if result.modified_count != 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already acknowledged this request")
    await _record_acknowledged(batch, "portal", actor_type="user", actor_user_id=str(user.id))
    return await RiskAcknowledgementBatch.get(batch.id)


async def _record_acknowledged(batch: RiskAcknowledgementBatch, via: str, *, actor_type: str, actor_user_id: str | None):
    await audit_service.record(
        "Risk Acknowledged",
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        project_id=batch.project_id,
        target_type="risk_acknowledgement",
        target_id=str(batch.id),
        metadata={"via": via, "items": len(batch.items)},
    )
    project = await Project.get(batch.project_id)
    await notification_service.notify(
        "risk.acknowledged",
        project_id=batch.project_id,
        title="Risk acknowledged",
        body=f"A recipient acknowledged {len(batch.items)} accepted risk(s) in {project.name if project else 'a project'}.",
        link=f"/projects/{batch.project_id}/vulnerabilities?view=risk",
    )


# --- CSV ---------------------------------------------------------------------------------------------

_CSV_COLUMNS = [
    ("Severity", "severity"),
    ("Rule", "rule_name"),
    ("Rule ID", "rule_id"),
    ("Kind", "kind"),
    ("File", "file_path"),
    ("Requested by", "requested_by_email"),
    ("Requested at", "requested_at"),
    ("Accepted by", "reviewed_by_email"),
    ("Accepted at", "reviewed_at"),
    ("Auto-accepted", "auto_accepted"),
    ("Justification", "comment"),
]


def _csv_cell(value) -> str:
    """Stringify one cell, defusing spreadsheet formulas: a cell starting with = + - @ (or a tab or CR)
    is executed by Excel, so it is prefixed with an apostrophe."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return as_utc(value).strftime("%Y-%m-%d %H:%M UTC")
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def render_csv(items: list[AckItem]) -> bytes:
    """UTF-8 with a BOM, which is what makes Excel read non-ASCII text correctly."""
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([name for name, _ in _CSV_COLUMNS])
    for i in items:
        writer.writerow([_csv_cell(getattr(i, attr)) for _, attr in _CSV_COLUMNS])
    return b"\xef\xbb\xbf" + out.getvalue().encode("utf-8")

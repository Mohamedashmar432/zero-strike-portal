"""Risk acceptances of a project and the admin-sent acknowledgement of them
(docs/RISK_ACCEPT_REVIEW_AND_VULN_REDESIGN.md).

Reads are member-gated and mask recipient addresses; sending, resending and the report previews are portal
admin only; the project owner acknowledges from the portal; and a recipient may acknowledge from the
emailed link with no sign-in, through the two public routes at the bottom (token in the body, per-IP rate
limit, one identical 404 for every bad token).
"""

import re
from datetime import datetime, timezone

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.core import rate_limit
from app.core.deps import get_current_user, require_admin
from app.core.timeutils import as_utc
from app.models.risk_acknowledgement import AckItem, RiskAcknowledgementBatch
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.schemas.risk_acknowledgement import (
    AckItemOut,
    AckRecipientOut,
    PublicAckItem,
    PublicAckLookupResponse,
    PublicAckRequest,
    PublicAckResult,
    RiskAcceptanceListResponse,
    RiskAcceptanceRow,
    RiskAckBatchOut,
    RiskAckCreateRequest,
    RiskAckListResponse,
)
from app.services import project_service, risk_acknowledgement_service as svc
from app.services import pdf_report_service

router = APIRouter(tags=["risk-acknowledgements"])
public_router = APIRouter(tags=["risk-acknowledgements"])

_PUBLIC_ITEM_CAP = 500
_PUBLIC_LIMIT = (10, 600)  # attempts, seconds -- per IP, shared by lookup and acknowledge


async def _batch_or_404(project_id: str, batch_id: str) -> RiskAcknowledgementBatch:
    batch = await RiskAcknowledgementBatch.get(batch_id) if PydanticObjectId.is_valid(batch_id) else None
    if batch is None or batch.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Acknowledgement request not found")
    return batch


async def _batch_out(
    batch: RiskAcknowledgementBatch, *, is_admin: bool, live: dict, emails: dict[str, str], with_items: bool = False
) -> RiskAckBatchOut:
    show = (lambda e: e) if is_admin else svc.mask_email
    state = svc.state_for(batch, live)
    return RiskAckBatchOut(
        id=str(batch.id),
        project_id=batch.project_id,
        created_at=as_utc(batch.created_at),
        created_by_email=emails.get(batch.created_by_user_id),
        message=batch.message,
        item_count=len(batch.items),
        recipients=[
            AckRecipientOut(
                email=show(r.email),
                is_project_owner=r.is_project_owner,
                delivery=r.delivery,
                send_count=r.send_count,
                last_sent_at=as_utc(r.last_sent_at),
                token_expires_at=as_utc(r.token_expires_at),
                acknowledged_at=as_utc(r.acknowledged_at),
                acknowledged_by=show(r.acknowledged_by) if r.acknowledged_by else None,
                acknowledged_via=r.acknowledged_via,
            )
            for r in batch.recipients
        ],
        items=[_item_out(i, live) for i in batch.items] if with_items else None,
        **state,
    )


def _item_out(i: AckItem, live: dict) -> AckItemOut:
    return AckItemOut(
        vulnerability_id=i.vulnerability_id,
        rule_id=i.rule_id,
        rule_name=i.rule_name,
        severity=i.severity,
        kind=i.kind,
        file_path=i.file_path,
        requested_by_email=i.requested_by_email,
        requested_at=as_utc(i.requested_at),
        reviewed_by_email=i.reviewed_by_email,
        reviewed_at=as_utc(i.reviewed_at),
        comment=i.comment,
        auto_accepted=i.auto_accepted,
        current=svc.item_is_current(i, live),
    )


async def _outs(batches: list[RiskAcknowledgementBatch], user: User, with_items: bool = False) -> list[RiskAckBatchOut]:
    live = await svc.live_reviews(batches)
    emails = await svc.emails_for({b.created_by_user_id for b in batches})
    return [
        await _batch_out(b, is_admin=user.role == "admin", live=live, emails=emails, with_items=with_items)
        for b in batches
    ]


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


def _filename(project_name: str, ext: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-") or "project"
    return f"risk-acceptance-{slug}-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.{ext}"


# --- the Risk accepted tab ---------------------------------------------------------------------------


@router.get("/projects/{project_id}/risk-acceptances", response_model=RiskAcceptanceListResponse)
async def list_risk_acceptances(
    project_id: str,
    review_status: str = Query("all", pattern="^(all|accepted|pending)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    """Every finding of the project with an accepted-risk review: who asked and why, who approved and
    when, and whether the owner has acknowledged that decision."""
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    is_admin = user.role == "admin"

    base = {"project_id": project_id, "review.kind": "accepted_risk"}
    statuses = ["accepted", "pending"] if review_status == "all" else [review_status]
    query = Vulnerability.find({**base, "review.status": {"$in": statuses}})
    total = await query.count()
    rows = await query.sort("-review.requested_at").skip((page - 1) * page_size).limit(page_size).to_list()
    accepted_count = await Vulnerability.find({**base, "review.status": "accepted"}).count()
    pending_count = await Vulnerability.find({**base, "review.status": "pending"}).count()

    batches = await RiskAcknowledgementBatch.find({"project_id": project_id}).sort("-created_at").limit(50).to_list()
    live = await svc.live_reviews(batches)
    show = (lambda e: e) if is_admin else svc.mask_email
    ack_emails = await svc.emails_for(
        {v.review.requested_by_user_id for v in rows}
        | {v.review.reviewed_by_user_id for v in rows if v.review.reviewed_by_user_id}
    )

    # (vulnerability, decision) -> the newest batch that covers exactly that decision.
    covering: dict[tuple[str, datetime | None], RiskAcknowledgementBatch] = {}
    for b in batches:  # newest first
        for i in b.items:
            covering.setdefault((i.vulnerability_id, as_utc(i.reviewed_at)), b)

    def ack_for(v: Vulnerability):
        if v.review.status != "accepted":
            return "none", None, None
        b = covering.get((str(v.id), as_utc(v.review.reviewed_at)))
        if b is None:
            return "none", None, None
        done = next((r for r in b.recipients if r.acknowledged_at), None)
        if done:
            return "acknowledged", b, done
        return ("awaiting" if svc.state_for(b, live)["state"] == "pending" else "none"), b, None

    out_rows = []
    for v in rows:
        ack, batch, done = ack_for(v)
        out_rows.append(
            RiskAcceptanceRow(
                vulnerability_id=str(v.id),
                fingerprint=v.fingerprint,
                rule_id=v.current_rule_id,
                rule_name=v.current_rule_name,
                severity=v.current_severity,
                kind=v.current_kind,
                file_path=v.review.file_path,
                review_status=v.review.status,
                comment=v.review.request_comment,
                requested_by_email=ack_emails.get(v.review.requested_by_user_id),
                requested_at=as_utc(v.review.requested_at),
                reviewed_by_email=ack_emails.get(v.review.reviewed_by_user_id or ""),
                reviewed_at=as_utc(v.review.reviewed_at),
                auto_accepted=(v.review.review_comment or "").startswith("Auto-accepted"),
                ack_state=ack,
                acknowledged_at=as_utc(done.acknowledged_at) if done else None,
                acknowledged_by=show(done.acknowledged_by) if done and done.acknowledged_by else None,
                batch_id=str(batch.id) if batch and ack != "none" else None,
            )
        )

    # Accepted risks no acknowledged batch covers: what "send for acknowledgement" would add.
    unacknowledged = 0
    if accepted_count:
        acked = {
            (i.vulnerability_id, as_utc(i.reviewed_at))
            for b in batches
            if any(r.acknowledged_at for r in b.recipients)
            for i in b.items
        }
        unacknowledged = sum(
            1 for v in await svc.eligible_items(project_id) if (str(v.id), as_utc(v.review.reviewed_at)) not in acked
        )

    latest = (await _outs(batches[:1], user))[0] if batches else None
    return RiskAcceptanceListResponse(
        items=out_rows,
        total=total,
        page=page,
        page_size=page_size,
        accepted_count=accepted_count,
        pending_count=pending_count,
        unacknowledged_count=unacknowledged,
        latest_batch=latest,
    )


@router.get("/projects/{project_id}/risk-acceptances/report.pdf")
async def risk_acceptances_pdf(project_id: str, user: User = Depends(require_admin)):
    """Preview of what an acknowledgement request would attach, from the live accepted risks."""
    project = await project_service.get_project_or_404(project_id)
    items = await svc.snapshot(await svc.eligible_items(project_id))
    pdf = await pdf_report_service.render_risk_acceptance_pdf(project.name, items)
    return _download(pdf, "application/pdf", _filename(project.name, "pdf"))


@router.get("/projects/{project_id}/risk-acceptances/report.csv")
async def risk_acceptances_csv(project_id: str, user: User = Depends(require_admin)):
    project = await project_service.get_project_or_404(project_id)
    items = await svc.snapshot(await svc.eligible_items(project_id))
    return _download(svc.render_csv(items), "text/csv; charset=utf-8", _filename(project.name, "csv"))


# --- acknowledgement batches -------------------------------------------------------------------------


@router.post("/projects/{project_id}/risk-acknowledgements", response_model=RiskAckBatchOut, status_code=201)
async def create_risk_acknowledgement(
    project_id: str, payload: RiskAckCreateRequest, user: User = Depends(require_admin)
):
    """Email the project owner (plus any extra addresses) the PDF and CSV of every accepted risk, with a
    link to acknowledge. Admin only, and never triggered automatically."""
    project = await project_service.get_project_or_404(project_id)
    batch = await svc.create_and_send(project, user, payload.extra_recipients, payload.message)
    return (await _outs([batch], user, with_items=True))[0]


@router.get("/projects/{project_id}/risk-acknowledgements", response_model=RiskAckListResponse)
async def list_risk_acknowledgements(project_id: str, user: User = Depends(get_current_user)):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    batches = await RiskAcknowledgementBatch.find({"project_id": project_id}).sort("-created_at").limit(50).to_list()
    return RiskAckListResponse(items=await _outs(batches, user))


@router.get("/projects/{project_id}/risk-acknowledgements/{batch_id}", response_model=RiskAckBatchOut)
async def get_risk_acknowledgement(project_id: str, batch_id: str, user: User = Depends(get_current_user)):
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    batch = await _batch_or_404(project_id, batch_id)
    return (await _outs([batch], user, with_items=True))[0]


@router.get("/projects/{project_id}/risk-acknowledgements/{batch_id}/report.pdf")
async def risk_acknowledgement_pdf(project_id: str, batch_id: str, user: User = Depends(require_admin)):
    project = await project_service.get_project_or_404(project_id)
    batch = await _batch_or_404(project_id, batch_id)
    pdf = await pdf_report_service.render_risk_acceptance_pdf(project.name, batch.items, batch.created_at)
    return _download(pdf, "application/pdf", _filename(project.name, "pdf"))


@router.get("/projects/{project_id}/risk-acknowledgements/{batch_id}/report.csv")
async def risk_acknowledgement_csv(project_id: str, batch_id: str, user: User = Depends(require_admin)):
    project = await project_service.get_project_or_404(project_id)
    batch = await _batch_or_404(project_id, batch_id)
    return _download(svc.render_csv(batch.items), "text/csv; charset=utf-8", _filename(project.name, "csv"))


@router.post("/projects/{project_id}/risk-acknowledgements/{batch_id}/resend", response_model=RiskAckBatchOut)
async def resend_risk_acknowledgement(project_id: str, batch_id: str, user: User = Depends(require_admin)):
    project = await project_service.get_project_or_404(project_id)
    batch = await _batch_or_404(project_id, batch_id)
    batch = await svc.resend(batch, project, user)
    return (await _outs([batch], user, with_items=True))[0]


@router.post("/projects/{project_id}/risk-acknowledgements/{batch_id}/acknowledge", response_model=RiskAckBatchOut)
async def acknowledge_risk_in_portal(project_id: str, batch_id: str, user: User = Depends(get_current_user)):
    """The project owner's own acknowledgement. A portal admin who is not the owner cannot do it for them."""
    await project_service.get_project_or_404(project_id)
    await project_service.require_member(project_id, user)
    batch = await _batch_or_404(project_id, batch_id)
    batch = await svc.acknowledge_in_portal(batch, user)
    return (await _outs([batch], user, with_items=True))[0]


# --- public link acknowledgement (no sign-in) --------------------------------------------------------


def _not_found() -> HTTPException:
    # One answer for an unknown, used or expired token, so the route is no oracle for which tokens exist.
    return HTTPException(status.HTTP_404_NOT_FOUND, "This link is not valid")


@public_router.post("/risk-acknowledgements/lookup", response_model=PublicAckLookupResponse)
async def lookup_risk_acknowledgement(payload: PublicAckRequest, request: Request):
    rate_limit.enforce(f"risk-ack:{rate_limit.client_ip(request)}", *_PUBLIC_LIMIT)
    found = await svc.lookup_by_token(payload.token)
    if found is None:
        raise _not_found()
    batch, recipient, project_name = found
    return PublicAckLookupResponse(
        project_name=project_name,
        created_at=as_utc(batch.created_at),
        message=batch.message,
        expires_at=as_utc(recipient.token_expires_at),
        item_count=len(batch.items),
        items=[
            PublicAckItem(
                rule_name=i.rule_name or i.rule_id,
                severity=i.severity,
                kind=i.kind,
                file_path=i.file_path,
                comment=i.comment,
                accepted_at=as_utc(i.reviewed_at),
                auto_accepted=i.auto_accepted,
            )
            for i in batch.items[:_PUBLIC_ITEM_CAP]
        ],
    )


@public_router.post("/risk-acknowledgements/acknowledge", response_model=PublicAckResult)
async def acknowledge_risk_by_link(payload: PublicAckRequest, request: Request):
    rate_limit.enforce(f"risk-ack:{rate_limit.client_ip(request)}", *_PUBLIC_LIMIT)
    batch = await svc.acknowledge_by_token(payload.token)
    if batch is None:
        raise _not_found()
    from app.models.project import Project

    project = await Project.get(batch.project_id)
    return PublicAckResult(
        acknowledged=True, project_name=project.name if project else "Deleted project", item_count=len(batch.items)
    )

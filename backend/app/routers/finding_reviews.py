"""Admin review queue for findings members asked to stop blocking CI (docs/FINDING_REVIEW.md).

Members create a request through the vulnerability status route; deciding is portal-admin only,
because an accepted review exempts the finding from every later CI gate on that repo.
"""

from beanie import PydanticObjectId
from beanie.operators import In
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import require_admin
from app.models.project import Project
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.schemas.finding_review import (
    FindingReviewDecision,
    FindingReviewItem,
    FindingReviewListResponse,
    FindingReviewRevoke,
)
from app.services import finding_review_service

router = APIRouter(tags=["finding-reviews"])

_STATUSES = ("pending", "accepted", "rejected", "revoked")


async def _items(rows: list[Vulnerability]) -> list[FindingReviewItem]:
    project_ids = [PydanticObjectId(p) for p in {v.project_id for v in rows} if PydanticObjectId.is_valid(p)]
    projects = {str(p.id): p.name for p in await Project.find(In(Project.id, project_ids)).to_list()}
    user_ids = set()
    for v in rows:
        user_ids.add(v.review.requested_by_user_id)
        if v.review.reviewed_by_user_id:
            user_ids.add(v.review.reviewed_by_user_id)
    valid = [PydanticObjectId(u) for u in user_ids if PydanticObjectId.is_valid(u)]
    emails = {str(u.id): u.email for u in await User.find(In(User.id, valid)).to_list()} if valid else {}
    return [
        FindingReviewItem(
            vulnerability_id=str(v.id),
            project_id=v.project_id,
            # A project deleted since the request has no name to show, and must not be linked.
            project_name=projects.get(v.project_id),
            fingerprint=v.fingerprint,
            severity=v.current_severity,
            kind_of_finding=v.current_kind,
            rule_id=v.current_rule_id,
            rule_name=v.current_rule_name,
            message=v.current_message,
            location=v.current_location,
            vulnerability_status=v.status,
            review=v.review.model_dump(),
            requested_by_email=emails.get(v.review.requested_by_user_id),
            reviewed_by_email=emails.get(v.review.reviewed_by_user_id or ""),
        )
        for v in rows
    ]


async def _get_reviewed_or_404(vulnerability_id: str) -> Vulnerability:
    v = await Vulnerability.get(vulnerability_id) if PydanticObjectId.is_valid(vulnerability_id) else None
    if v is None or v.review is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    return v


@router.get("/admin/finding-reviews", response_model=FindingReviewListResponse)
async def list_finding_reviews(
    status_filter: str = Query(default="pending", alias="status"),
    user: User = Depends(require_admin),
):
    if status_filter not in _STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown status filter")
    rows = (
        await Vulnerability.find({"review.status": status_filter})
        .sort("-review.requested_at")
        .limit(500)
        .to_list()
    )
    # Always the full queue depth, so the nav badge is right while browsing another tab.
    pending = await Vulnerability.find({"review.status": "pending"}).count()
    return FindingReviewListResponse(items=await _items(rows), pending_count=pending)


@router.post("/admin/finding-reviews/{vulnerability_id}/decide", response_model=FindingReviewItem)
async def decide_finding_review(
    vulnerability_id: str, payload: FindingReviewDecision, user: User = Depends(require_admin)
):
    v = await _get_reviewed_or_404(vulnerability_id)
    v = await finding_review_service.decide(v, payload.decision == "accept", payload.comment, user)
    return (await _items([v]))[0]


@router.post("/admin/finding-reviews/{vulnerability_id}/revoke", response_model=FindingReviewItem)
async def revoke_finding_review(
    vulnerability_id: str, payload: FindingReviewRevoke, user: User = Depends(require_admin)
):
    v = await _get_reviewed_or_404(vulnerability_id)
    v = await finding_review_service.revoke(v, payload.comment, user)
    return (await _items([v]))[0]

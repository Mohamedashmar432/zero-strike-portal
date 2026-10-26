from typing import Literal

from pydantic import BaseModel

from app.models.finding import LocationEmbedded
from app.models.vulnerability import FindingReview


class FindingReviewDecision(BaseModel):
    decision: Literal["accept", "reject"]
    comment: str | None = None


class FindingReviewRevoke(BaseModel):
    comment: str


class FindingReviewItem(BaseModel):
    vulnerability_id: str
    project_id: str
    project_name: str | None
    fingerprint: str
    severity: str | None
    kind_of_finding: str | None
    rule_id: str | None
    rule_name: str | None
    message: str | None
    location: LocationEmbedded | None
    vulnerability_status: str
    review: FindingReview
    requested_by_email: str | None = None
    reviewed_by_email: str | None = None


class FindingReviewListResponse(BaseModel):
    items: list[FindingReviewItem]
    pending_count: int


class ExemptionOut(BaseModel):
    """One accepted exemption as the scanner receives it: skip a finding only when both match."""

    fingerprint: str
    file: str
    kind: Literal["false_positive", "accepted_risk"]

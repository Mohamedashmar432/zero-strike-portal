from datetime import datetime

from pydantic import BaseModel, Field

from app.models.auto_fix_quota import AutoFixQuotaRequestStatus


class ScanAutoFixQuotaResponse(BaseModel):
    scan_id: str
    project_id: str
    #: Global base allowance (RemediationSettings.auto_fix_findings_per_scan).
    default_limit: int
    #: Extra headroom approved by an admin for this scan.
    extra_granted: int
    #: default_limit + extra_granted.
    limit: int
    #: Distinct findings on this scan that already have a fix proposal.
    used: int
    remaining: int
    #: Lets the UI show "request pending" instead of offering a second request.
    pending_request_count: int


class AutoFixQuotaRequestCreate(BaseModel):
    requested_additional: int = Field(ge=1, le=500)
    #: Required. An admin approving extra AI spend needs the justification.
    reason: str = Field(min_length=1, max_length=2000)


class AutoFixQuotaRequestDecision(BaseModel):
    approve: bool
    #: Omit to grant exactly what was requested; set to grant a different amount.
    granted_additional: int | None = Field(default=None, ge=1, le=500)
    decision_note: str | None = Field(default=None, max_length=2000)


class AutoFixQuotaRequestOut(BaseModel):
    id: str
    scan_id: str
    project_id: str
    #: Resolved for display so the admin table needs no extra round-trips.
    project_name: str | None = None
    requested_by: str
    requested_by_email: str | None = None
    requested_additional: int
    reason: str
    status: AutoFixQuotaRequestStatus
    granted_additional: int | None = None
    decision_note: str | None = None
    decided_by: str | None = None
    decided_by_email: str | None = None
    decided_at: datetime | None = None
    created_at: datetime


class AutoFixQuotaRequestListResponse(BaseModel):
    items: list[AutoFixQuotaRequestOut]
    pending_count: int

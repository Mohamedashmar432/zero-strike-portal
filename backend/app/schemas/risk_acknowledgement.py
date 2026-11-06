from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.risk_acknowledgement import AckVia, Delivery

BatchState = Literal["pending", "acknowledged", "superseded", "expired"]


class RiskAckCreateRequest(BaseModel):
    """Extra recipients may be any address (the dialog confirms the count); the project owner is always
    included. Validated and capped in the service."""

    extra_recipients: list[str] = Field(default_factory=list, max_length=50)
    message: str | None = Field(default=None, max_length=2000)


class AckItemOut(BaseModel):
    vulnerability_id: str
    rule_id: str | None
    rule_name: str | None
    severity: str | None
    kind: str | None
    file_path: str
    requested_by_email: str | None
    requested_at: datetime
    reviewed_by_email: str | None
    reviewed_at: datetime | None
    comment: str
    auto_accepted: bool
    #: False once the finding was re-decided or revoked after this batch was sent.
    current: bool


class AckRecipientOut(BaseModel):
    #: Masked ("a***@e***.com") unless the caller is a portal admin.
    email: str
    is_project_owner: bool
    delivery: Delivery
    send_count: int
    last_sent_at: datetime | None
    token_expires_at: datetime | None
    acknowledged_at: datetime | None
    acknowledged_by: str | None
    acknowledged_via: AckVia | None


class RiskAckBatchOut(BaseModel):
    id: str
    project_id: str
    created_at: datetime
    created_by_email: str | None
    message: str | None
    item_count: int
    state: BatchState
    items_current: int
    items_superseded: int
    recipients_sent: int
    recipients_acknowledged: int
    recipients: list[AckRecipientOut]
    #: Only on the single-batch read; a list stays small.
    items: list[AckItemOut] | None = None


class RiskAckListResponse(BaseModel):
    items: list[RiskAckBatchOut]


class RiskAcceptanceRow(BaseModel):
    vulnerability_id: str
    fingerprint: str
    rule_id: str | None
    rule_name: str | None
    severity: str | None
    kind: str | None
    file_path: str
    review_status: Literal["pending", "accepted"]
    comment: str
    requested_by_email: str | None
    requested_at: datetime
    reviewed_by_email: str | None
    reviewed_at: datetime | None
    auto_accepted: bool
    #: acknowledged: a recipient acknowledged this very decision. awaiting: it is in a batch that is still
    #: open. none: never sent (or a pending request, which has nothing to acknowledge yet).
    ack_state: Literal["acknowledged", "awaiting", "none"]
    acknowledged_at: datetime | None = None
    #: Masked unless the caller is a portal admin.
    acknowledged_by: str | None = None
    batch_id: str | None = None


class RiskAcceptanceListResponse(BaseModel):
    items: list[RiskAcceptanceRow]
    total: int
    page: int
    page_size: int
    accepted_count: int
    pending_count: int
    unacknowledged_count: int
    latest_batch: RiskAckBatchOut | None


class PublicAckRequest(BaseModel):
    token: str = Field(min_length=1, max_length=256)


class PublicAckItem(BaseModel):
    rule_name: str | None
    severity: str | None
    kind: str | None
    file_path: str
    comment: str
    accepted_at: datetime | None
    auto_accepted: bool


class PublicAckLookupResponse(BaseModel):
    project_name: str
    created_at: datetime
    message: str | None
    expires_at: datetime | None
    item_count: int
    items: list[PublicAckItem]


class PublicAckResult(BaseModel):
    acknowledged: bool
    project_name: str
    item_count: int

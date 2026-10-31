"""The live dependency alert ledger: dedupe record, in-portal feed and delivery record in one.

A row is inserted BEFORE anything is sent (claim-then-deliver), and the unique index on
(project, ecosystem, package, version, advisory) is the claim: a second run, a second replica or a retry
after a crash hits DuplicateKeyError and sends nothing, so an advisory alerts at most once. This is
deliberately not a Finding/Vulnerability -- those belong to a scan and drive counters, compliance and the
CI gate; the next scan turns the advisory into a real finding."""

from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import BaseModel, Field
from pymongo import IndexModel

AlertSeverity = Literal["critical", "high", "medium", "low"]
RETENTION_DAYS = 400


class AlertLocation(BaseModel):
    repo_scope_key: str
    repo_label: str = ""
    manifests: list[str] = Field(default_factory=list)  # <= 5
    direct: bool | None = None  # raw scanner data; never rendered
    inventory_scan_id: str | None = None
    inventory_scanned_at: datetime | None = None
    git_commit: str | None = None


class AlertDelivery(BaseModel):
    channels: int = 0  # webhook channels the event matched
    in_app: int = 0  # in-app notification rows written
    project_webhook: Literal["sent", "failed", "off"] = "off"
    project_email: Literal["sent", "failed", "not_configured", "off"] = "off"


class LiveDependencyAlert(Document):
    project_id: str
    advisory_id: str  # representative id
    advisory_ids: list[str] = Field(default_factory=list)  # id + aliases
    summary: str = ""
    ecosystem: str
    package: str
    package_norm: str
    version: str
    severity: AlertSeverity
    cvss_score: float | None = None
    malicious: bool = False
    published_at: datetime
    modified_at: datetime | None = None
    fixed_versions: list[str] = Field(default_factory=list)  # <= 3
    locations: list[AlertLocation] = Field(default_factory=list)
    run_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    delivery: AlertDelivery = Field(default_factory=AlertDelivery)

    class Settings:
        name = "live_dependency_alerts"
        indexes = [
            IndexModel(
                [("project_id", 1), ("ecosystem", 1), ("package_norm", 1), ("version", 1), ("advisory_id", 1)],
                unique=True,
            ),
            IndexModel([("project_id", 1), ("created_at", -1)]),
            IndexModel([("created_at", -1)]),
            IndexModel([("created_at", 1)], expireAfterSeconds=RETENTION_DAYS * 86400, name="created_at_ttl"),
        ]

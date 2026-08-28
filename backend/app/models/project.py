from datetime import datetime
from typing import Literal

from beanie import Document, Indexed
from pydantic import Field
from pymongo import IndexModel


class Project(Document):
    name: Indexed(str)  # type: ignore[valid-type]
    description: str | None = None
    owner_id: Indexed(str)  # type: ignore[valid-type]
    is_archived: bool = False
    scan_count: int = 0
    last_scan_at: datetime | None = None
    # Denormalized findings rollup, maintained by report_ingestion_service.ingest (delta on every
    # (re)scan) so the projects-list / project-detail stats don't re-aggregate the whole findings
    # collection per request. keys: critical/high/medium/low/info.
    total_findings: int = 0
    finding_severity_counts: dict[str, int] = Field(default_factory=dict)
    # None = inherit the workspace-wide default (see report_template_service, added in a
    # later task).
    report_template: Literal["standard", "executive"] | None = None

    # --- policy overrides ----------------------------------------------------
    # Every field below is None-means-inherit, twinned with a WorkspaceSettings field and
    # resolved by workspace_settings_service.effective_*. A project owner may set these;
    # the service enforces that an override can only ever tighten the workspace policy.
    scan_enable_secrets: bool | None = None
    scan_enable_sca: bool | None = None
    scan_enable_framework_checks: bool | None = None
    compliance_frameworks: list[str] | None = None
    compliance_audit_scope: Literal["latest", "history"] | None = None
    compliance_auto_audit_on_scan: bool | None = None
    compliance_evidence_retention_days: int | None = None
    # No twin for compliance_audit_ai_narrative on purpose: it authorises LLM spend, so it
    # stays workspace-only under require_admin.
    # Auto-fix: a project may switch it off, and may raise the confidence threshold. It can
    # neither switch it on against a workspace-wide disable nor lower the threshold --
    # enforced in effective_remediation_policy, not here.
    auto_fix_enabled: bool | None = None
    auto_fix_confidence_threshold: float | None = None

    created_at: datetime
    updated_at: datetime

    class Settings:
        name = "projects"
        indexes = [IndexModel([("owner_id", 1), ("is_archived", 1)])]  # standard list-view filter

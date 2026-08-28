from datetime import datetime, timezone
from typing import Literal

from beanie import Document
from pydantic import Field

ReportTemplate = Literal["standard", "executive"]
AuditScope = Literal["latest", "history"]


class WorkspaceSettings(Document):
    """Singleton — at most one document ever exists (see workspace_settings_service, which
    creates it lazily on first read). Workspace-wide defaults that apply to every project
    unless that project sets its own override.

    Every field here that a project may override has a nullable twin on Project, where
    `None` means inherit. The pairing is resolved in exactly one place per policy area
    (workspace_settings_service.effective_*), never re-derived at a call site.
    """

    default_report_template: ReportTemplate = "standard"

    # "Project BYOK": when True, each project brings its own AI provider + key and is fully
    # isolated -- a project's key serves only that project and never falls back to the
    # portal-wide provider, and a project without one has AI disabled entirely. When False
    # (the default) every project shares the admin's portal-wide provider, as it always has.
    # Read through ai_provider_config_service.byok_enabled(); enforced in
    # ai_provider_config_service.resolve_failover_configs().
    project_byok_enabled: bool = False

    # --- scan defaults -------------------------------------------------------
    # These three were hardcoded into the scanner argv in cloud_scan_service. The defaults
    # below are those hardcoded values, so an existing workspace behaves identically until
    # an admin actually changes one.
    scan_enable_secrets: bool = True
    scan_enable_sca: bool = True
    scan_enable_framework_checks: bool = True

    # --- compliance policy ---------------------------------------------------
    # Frameworks a project is assessed against by default; pre-selects the audit wizard.
    # Empty means "no default" -- the wizard then pre-selects every supported framework, as
    # it does today. Validated against SUPPORTED_FRAMEWORK_KEYS at the API layer.
    compliance_frameworks: list[str] = Field(default_factory=list)
    # Which findings count as evidence. "latest" is only each repo's most recent completed
    # scan (current posture); "history" is every finding ever ingested, including ones from
    # superseded scans. Used by every audit, hand-started or automatic -- it replaced the
    # question the old three-step wizard asked at run time.
    compliance_audit_scope: AuditScope = "latest"
    # Whether a hand-started audit also pays for the LLM narrative pass. Spend-bearing, so it
    # has NO project twin: it stays admin-owned, same rule as the auto-fix allowance. Verdicts
    # are always deterministic -- the narrative only writes prose for already-failing controls.
    compliance_audit_ai_narrative: bool = False
    # Run an audit automatically when a scan completes. Deterministic depth only (no LLM
    # call), so switching this on can never produce unbudgeted AI spend.
    compliance_auto_audit_on_scan: bool = False
    # Completed audits older than this are reaped by compliance_queue_service.poll_loop.
    # None = keep forever (today's behaviour).
    compliance_evidence_retention_days: int | None = None

    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: str | None = None

    class Settings:
        name = "workspace_settings"

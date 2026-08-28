"""The single owner of the WorkspaceSettings singleton, and the one place where a
project override is resolved against the workspace default.

Two rules hold for every resolver here, and nothing outside this module gets to re-derive
them:

1. `None` on the Project means inherit. It never means "off".
2. An override may only ever *tighten* the workspace policy. A project owner is not a
   portal admin: they may switch a capability off, and may raise a safety threshold, but
   they cannot switch on something the workspace disabled or lower a threshold beneath the
   workspace floor. Callers therefore never need to re-check the workspace value.

Spend-bearing policy (per-scan auto-fix allowance, blocking severities, quota grants) has
no project twin at all -- it stays in RemediationSettings under require_admin.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.project import Project
from app.models.workspace_settings import AuditScope, ReportTemplate, WorkspaceSettings


async def get_workspace_settings() -> WorkspaceSettings:
    settings = await WorkspaceSettings.find_one()
    if settings is None:
        settings = WorkspaceSettings()
        await settings.insert()
    return settings


async def update_workspace_settings(*, updated_by: str | None = None, **changed) -> WorkspaceSettings:
    """Apply a partial update. Callers pass only the fields the request actually set
    (`model_dump(exclude_unset=True)`), so an absent field is never confused with a null one.
    """
    settings = await get_workspace_settings()
    for field, value in changed.items():
        if not hasattr(settings, field):
            raise AttributeError(f"WorkspaceSettings has no field {field!r}")
        setattr(settings, field, value)
    settings.updated_at = datetime.now(timezone.utc)
    settings.updated_by = updated_by
    await settings.save()
    return settings


# --- resolvers ---------------------------------------------------------------


async def load_project(project_id: str | None) -> Project | None:
    """Project by id, or None — including when the id isn't a valid ObjectId.

    Beanie's `.get()` raises a ValidationError on a malformed id rather than returning None.
    Every caller here wants "resolve policy for this project, falling back to workspace
    defaults if it can't be found", and a scan must not fail because its project_id is stale
    or hand-written. Callers use this instead of Project.get.
    """
    if not project_id:
        return None
    try:
        return await Project.get(project_id)
    except Exception:
        return None


def _inherit(override, default):
    return default if override is None else override


async def effective_report_template(project: Project) -> ReportTemplate:
    if project.report_template is not None:
        return project.report_template
    return (await get_workspace_settings()).default_report_template


@dataclass(frozen=True)
class ScanOptions:
    enable_secrets: bool
    enable_sca: bool
    enable_framework_checks: bool


async def effective_scan_options(project: Project | None) -> ScanOptions:
    """Which scanner feature flags a scan of this project runs with.

    `project=None` is a scan with no project context (there is none today, but the
    scanner-created paths construct scans before the project is loaded) -- it gets the
    workspace defaults.
    """
    ws = await get_workspace_settings()
    if project is None:
        return ScanOptions(ws.scan_enable_secrets, ws.scan_enable_sca, ws.scan_enable_framework_checks)
    return ScanOptions(
        enable_secrets=_inherit(project.scan_enable_secrets, ws.scan_enable_secrets),
        enable_sca=_inherit(project.scan_enable_sca, ws.scan_enable_sca),
        enable_framework_checks=_inherit(
            project.scan_enable_framework_checks, ws.scan_enable_framework_checks
        ),
    )


@dataclass(frozen=True)
class CompliancePolicy:
    frameworks: list[str]
    audit_scope: AuditScope
    #: Workspace-only. Spend-bearing, so a project cannot switch the narrative pass on.
    audit_ai_narrative: bool
    auto_audit_on_scan: bool
    evidence_retention_days: int | None
    # Which of the above came from the project rather than the workspace -- so the UI can
    # say "inherited" vs "overridden here" without guessing.
    overridden: frozenset[str]


async def effective_compliance_policy(project: Project | None) -> CompliancePolicy:
    """The frameworks, evidence scope and depth every audit of this project runs with.

    This is what replaced the audit wizard's run-time questions: the answers are configured
    once, here, and both the hand-started audit and the automatic one read them from the same
    resolver rather than each carrying its own defaults.
    """
    ws = await get_workspace_settings()
    if project is None:
        return CompliancePolicy(
            list(ws.compliance_frameworks),
            ws.compliance_audit_scope,
            ws.compliance_audit_ai_narrative,
            ws.compliance_auto_audit_on_scan,
            ws.compliance_evidence_retention_days,
            frozenset(),
        )
    overridden = {
        name
        for name, value in (
            ("frameworks", project.compliance_frameworks),
            ("audit_scope", project.compliance_audit_scope),
            ("auto_audit_on_scan", project.compliance_auto_audit_on_scan),
            ("evidence_retention_days", project.compliance_evidence_retention_days),
        )
        if value is not None
    }
    return CompliancePolicy(
        frameworks=list(_inherit(project.compliance_frameworks, ws.compliance_frameworks)),
        audit_scope=_inherit(project.compliance_audit_scope, ws.compliance_audit_scope),
        audit_ai_narrative=ws.compliance_audit_ai_narrative,
        auto_audit_on_scan=_inherit(
            project.compliance_auto_audit_on_scan, ws.compliance_auto_audit_on_scan
        ),
        evidence_retention_days=_inherit(
            project.compliance_evidence_retention_days, ws.compliance_evidence_retention_days
        ),
        overridden=frozenset(overridden),
    )


@dataclass(frozen=True)
class RemediationPolicy:
    enabled: bool
    confidence_threshold: float
    overridden: frozenset[str]


async def effective_remediation_policy(project: Project | None) -> RemediationPolicy:
    """Auto-fix policy for one project. Tighten-only, enforced here rather than at write
    time so a workspace admin lowering the floor later cannot silently un-tighten a project
    that had already opted into something stricter.
    """
    # Imported here rather than at module scope: remediation_settings_service imports no
    # models this module owns today, but keeping the edge local avoids a future cycle.
    from app.services import remediation_settings_service

    cfg = await remediation_settings_service.get_settings()
    if project is None:
        return RemediationPolicy(cfg.enabled, cfg.confidence_threshold, frozenset())

    overridden = set()
    # A project may disable auto-fix. It may not enable it when the workspace disabled it.
    enabled = cfg.enabled and _inherit(project.auto_fix_enabled, cfg.enabled)
    if project.auto_fix_enabled is not None and enabled != cfg.enabled:
        overridden.add("enabled")

    # A project may raise the confidence bar, never lower it.
    threshold = cfg.confidence_threshold
    if project.auto_fix_confidence_threshold is not None:
        threshold = max(cfg.confidence_threshold, project.auto_fix_confidence_threshold)
        if threshold != cfg.confidence_threshold:
            overridden.add("confidence_threshold")

    return RemediationPolicy(enabled, threshold, frozenset(overridden))

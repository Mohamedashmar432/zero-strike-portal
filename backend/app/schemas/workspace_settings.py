from pydantic import BaseModel, Field, field_validator

from app.core.compliance_catalog import SUPPORTED_FRAMEWORK_KEYS
from app.models.workspace_settings import AuditScope


def _validate_frameworks(v: list[str] | None) -> list[str] | None:
    """Reject frameworks the evaluator refuses to run.

    Storing an unsupported key would let a project's saved policy pre-select a framework
    that the audit endpoint then rejects at trigger time -- config that cannot be acted on.
    """
    if v is None:
        return v
    bad = [k for k in v if k not in SUPPORTED_FRAMEWORK_KEYS]
    if bad:
        raise ValueError(
            f"Not available yet: {sorted(bad)}. Supported: {sorted(SUPPORTED_FRAMEWORK_KEYS)}."
        )
    return list(dict.fromkeys(v))  # dedupe, preserve order


class WorkspaceSettingsResponse(BaseModel):
    default_report_template: str
    project_byok_enabled: bool
    scan_enable_secrets: bool
    scan_enable_sca: bool
    scan_enable_framework_checks: bool
    compliance_frameworks: list[str]
    compliance_audit_scope: AuditScope
    compliance_audit_ai_narrative: bool
    compliance_auto_audit_on_scan: bool
    compliance_evidence_retention_days: int | None


class WorkspaceSettingsUpdateRequest(BaseModel):
    """All fields optional — a PUT patches only what it sends (exclude_unset in the router).

    `default_report_template` and `project_byok_enabled` are deliberately absent: they are
    owned by /report-templates/settings and /ai-settings respectively, and a second writer
    for the same field is how two screens end up disagreeing.
    """

    scan_enable_secrets: bool | None = None
    scan_enable_sca: bool | None = None
    scan_enable_framework_checks: bool | None = None
    compliance_frameworks: list[str] | None = None
    compliance_audit_scope: AuditScope | None = None
    # Spend-bearing, so it lives here (admin-only) and has no project twin.
    compliance_audit_ai_narrative: bool | None = None
    compliance_auto_audit_on_scan: bool | None = None
    # 0 is not "keep forever" -- null is. A 0-day retention would reap an audit the moment
    # it completed, which is never what someone means.
    compliance_evidence_retention_days: int | None = Field(default=None, ge=1, le=3650)

    _check_frameworks = field_validator("compliance_frameworks")(_validate_frameworks)


class ProjectPolicyResponse(BaseModel):
    """A project's own overrides plus what they currently resolve to.

    Both halves are returned together so the UI can render "Inherited (SOC 2)" vs
    "Overridden here" without a second request and without re-deriving the precedence
    rules in TypeScript.
    """

    # raw overrides — None means inherit
    scan_enable_secrets: bool | None
    scan_enable_sca: bool | None
    scan_enable_framework_checks: bool | None
    compliance_frameworks: list[str] | None
    compliance_audit_scope: AuditScope | None
    compliance_auto_audit_on_scan: bool | None
    compliance_evidence_retention_days: int | None
    auto_fix_enabled: bool | None
    auto_fix_confidence_threshold: float | None
    report_template: str | None

    # resolved values, after workspace defaults and the tighten-only rule
    effective_scan_enable_secrets: bool
    effective_scan_enable_sca: bool
    effective_scan_enable_framework_checks: bool
    effective_compliance_frameworks: list[str]
    effective_compliance_audit_scope: AuditScope
    #: Workspace-owned; shown read-only on the project surface so it is clear why an audit
    #: does or does not include AI prose.
    effective_compliance_audit_ai_narrative: bool
    effective_compliance_auto_audit_on_scan: bool
    effective_compliance_evidence_retention_days: int | None
    effective_auto_fix_enabled: bool
    effective_auto_fix_confidence_threshold: float
    effective_report_template: str

    # workspace values, so the UI can name what is being inherited from
    workspace_auto_fix_enabled: bool
    workspace_auto_fix_confidence_threshold: float

    can_manage: bool


class ProjectPolicyUpdateRequest(BaseModel):
    """Every field is nullable-and-optional, which means two distinct things:
    absent = leave as-is, explicit null = clear the override and go back to inheriting.
    """

    scan_enable_secrets: bool | None = None
    scan_enable_sca: bool | None = None
    scan_enable_framework_checks: bool | None = None
    compliance_frameworks: list[str] | None = None
    compliance_audit_scope: AuditScope | None = None
    compliance_auto_audit_on_scan: bool | None = None
    compliance_evidence_retention_days: int | None = Field(default=None, ge=1, le=3650)
    auto_fix_enabled: bool | None = None
    auto_fix_confidence_threshold: float | None = Field(default=None, ge=0, le=100)

    _check_frameworks = field_validator("compliance_frameworks")(_validate_frameworks)

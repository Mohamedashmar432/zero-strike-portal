import { apiFetch } from "./client";

/** Which findings an audit counts as evidence. */
export type ComplianceAuditScope = "latest" | "history";

/** Workspace-wide defaults (portal admin writes, any signed-in user reads). */
export interface WorkspaceSettings {
  default_report_template: string;
  project_byok_enabled: boolean;
  scan_enable_secrets: boolean;
  scan_enable_sca: boolean;
  scan_enable_framework_checks: boolean;
  compliance_frameworks: string[];
  compliance_audit_scope: ComplianceAuditScope;
  /** Spend-bearing, so admin-only: no project can switch the narrative pass on for itself. */
  compliance_audit_ai_narrative: boolean;
  compliance_auto_audit_on_scan: boolean;
  compliance_evidence_retention_days: number | null;
}

/** Only the fields this surface owns — report template and BYOK are written by their own pages. */
export type WorkspaceSettingsUpdate = Partial<
  Pick<
    WorkspaceSettings,
    | "scan_enable_secrets"
    | "scan_enable_sca"
    | "scan_enable_framework_checks"
    | "compliance_frameworks"
    | "compliance_audit_scope"
    | "compliance_audit_ai_narrative"
    | "compliance_auto_audit_on_scan"
    | "compliance_evidence_retention_days"
  >
>;

export function getWorkspaceSettings() {
  return apiFetch<WorkspaceSettings>("/workspace-settings");
}

export function updateWorkspaceSettings(payload: WorkspaceSettingsUpdate) {
  return apiFetch<WorkspaceSettings>("/workspace-settings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

/**
 * A project's overrides and what they resolve to. Both halves come from the backend so the
 * inherit/override precedence is decided in exactly one place — never re-derived here.
 */
export interface ProjectPolicy {
  scan_enable_secrets: boolean | null;
  scan_enable_sca: boolean | null;
  scan_enable_framework_checks: boolean | null;
  compliance_frameworks: string[] | null;
  compliance_audit_scope: ComplianceAuditScope | null;
  compliance_auto_audit_on_scan: boolean | null;
  compliance_evidence_retention_days: number | null;
  auto_fix_enabled: boolean | null;
  auto_fix_confidence_threshold: number | null;
  report_template: string | null;

  effective_scan_enable_secrets: boolean;
  effective_scan_enable_sca: boolean;
  effective_scan_enable_framework_checks: boolean;
  effective_compliance_frameworks: string[];
  effective_compliance_audit_scope: ComplianceAuditScope;
  effective_compliance_audit_ai_narrative: boolean;
  effective_compliance_auto_audit_on_scan: boolean;
  effective_compliance_evidence_retention_days: number | null;
  effective_auto_fix_enabled: boolean;
  effective_auto_fix_confidence_threshold: number;
  effective_report_template: string;

  workspace_auto_fix_enabled: boolean;
  workspace_auto_fix_confidence_threshold: number;

  can_manage: boolean;
}

/**
 * `null` on a field means "clear the override, inherit again" — a real edit, distinct from
 * omitting the field, which leaves it untouched.
 */
export type ProjectPolicyUpdate = Partial<{
  scan_enable_secrets: boolean | null;
  scan_enable_sca: boolean | null;
  scan_enable_framework_checks: boolean | null;
  compliance_frameworks: string[] | null;
  compliance_audit_scope: ComplianceAuditScope | null;
  compliance_auto_audit_on_scan: boolean | null;
  compliance_evidence_retention_days: number | null;
  auto_fix_enabled: boolean | null;
  auto_fix_confidence_threshold: number | null;
}>;

export function getProjectPolicy(projectId: string) {
  return apiFetch<ProjectPolicy>(`/projects/${projectId}/policy`);
}

export function updateProjectPolicy(projectId: string, payload: ProjectPolicyUpdate) {
  return apiFetch<ProjectPolicy>(`/projects/${projectId}/policy`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

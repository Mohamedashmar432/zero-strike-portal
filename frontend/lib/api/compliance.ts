/**
 * Project-level compliance audits. A distinct pipeline from ai.ts (analysis) and
 * auto-fix.ts (remediation), but the third consumer of the same async-job envelope
 * (AiAnalysisStatus + started_at/progress_*) so it reuses the shared polling helpers.
 *
 * Control status is computed deterministically by the backend from scanner findings.
 * `ai_explanation` / `ai_remediation` are prose only -- they never determine `status`.
 */
import type { AiAnalysisStatus } from "./ai";
import { apiFetch } from "./client";

export type ControlStatus =
  | "pass"
  | "fail"
  | "partial"
  | "not_applicable"
  | "needs_manual_review";

export type AuditScope = "latest" | "history";
export type AuditDepth = "deterministic" | "with_ai_narrative";

export type ControlSummary = {
  id: string;
  title: string;
  reference: string;
  domain: string;
  description: string;
  recommendation: string;
  // False for governance/process controls no code scanner can evidence.
  code_assessable: boolean;
  manual_reason: string | null;
};

export type Framework = {
  key: string;
  title: string;
  scope_note: string;
  controls_total: number;
  assessed_total: number;
  controls: ControlSummary[];
};

export type ControlEvidence = {
  fingerprint: string;
  scan_id: string;
  rule_id: string | null;
  severity: string | null;
  file: string;
  line: number | null;
  message: string;
};

export type ControlResult = {
  framework: string;
  control_id: string;
  control_title: string;
  control_reference: string;
  domain: string;
  description: string;
  recommendation: string;
  status: ControlStatus;
  rationale: string;
  ai_explanation: string | null;
  ai_remediation: string | null;
  evidence: ControlEvidence[];
  // Exact match count; may exceed evidence.length, which is capped by the backend.
  evidence_total: number;
  severity_counts: Record<string, number>;
};

export type FrameworkSummary = {
  framework: string;
  framework_title: string;
  scope_note: string;
  controls_total: number;
  assessed_total: number;
  passed: number;
  failed: number;
  partial: number;
  not_applicable: number;
  needs_manual_review: number;
  // Percentage of *code-assessable* controls that passed. NOT a compliance percentage -- the
  // manual-only controls are not in the denominator. Always render it next to coverage_percent.
  compliance_score: number;
  // assessed_total / controls_total, as a percentage: how much of the framework a code scanner
  // can speak to at all, and so the ceiling on the number above.
  coverage_percent: number;
};

/** The audit without its control bodies -- what the project's history list renders. */
export type ComplianceAuditSummary = {
  id: string;
  project_id: string;
  frameworks: string[];
  scope: AuditScope;
  depth: AuditDepth;
  status: AiAnalysisStatus;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  progress_completed: number;
  progress_total: number;
  findings_total: number;
  summaries: FrameworkSummary[];
};

export type ComplianceAudit = ComplianceAuditSummary & {
  scan_ids: string[];
  // Repo coverage of the selected scope. repos_with_scans < repos_in_scope means the audit only
  // saw part of the project and the result under-represents it.
  repos_in_scope: number;
  repos_with_scans: number;
  newest_scan_at: string | null;
  findings_truncated: boolean;
  ai_note: string | null;
  // True when the backend returned an existing identical audit instead of re-running one.
  reused: boolean;
  controls: ControlResult[];
};

/**
 * Everything is optional. Sending `{}` runs the audit the project is *configured* for —
 * frameworks, evidence scope and AI depth all come from its Compliance Config, resolved
 * server-side so this file never re-derives the workspace/project precedence.
 */
export type RunAuditInput = {
  frameworks?: string[];
  scope?: AuditScope;
  project_repo_ids?: string[];
  depth?: AuditDepth;
  // Force a fresh run even when an identical completed audit over the same scans exists.
  refresh?: boolean;
};

export function listFrameworks() {
  return apiFetch<{ items: Framework[] }>("/compliance/frameworks");
}

export function listProjectAudits(projectId: string, page = 1, pageSize = 20) {
  return apiFetch<{
    items: ComplianceAuditSummary[];
    total: number;
    page: number;
    page_size: number;
  }>(`/projects/${projectId}/compliance-audits?page=${page}&page_size=${pageSize}`);
}

export function getAudit(auditId: string) {
  return apiFetch<ComplianceAudit>(`/compliance/audits/${auditId}`);
}

export function runAudit(projectId: string, input: RunAuditInput = {}) {
  return apiFetch<ComplianceAudit>(`/projects/${projectId}/compliance-audits`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export const CONTROL_STATUS_LABEL: Record<ControlStatus, string> = {
  pass: "Pass",
  fail: "Fail",
  partial: "Partial",
  not_applicable: "Not applicable",
  needs_manual_review: "Needs manual review",
};

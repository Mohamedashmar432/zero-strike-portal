import { apiFetch } from "./client";
import type { FindingKind, FindingLocation, Severity } from "./findings";
import type { ScanStatus, ScanType } from "./scans";
import type { Page } from "./users";
import type { PriorityTier } from "@/lib/priority";

// Mirrors backend/app/models/vulnerability.py -- keep these four literal unions in lockstep
// with the Python Literal types they're read from.
export type VulnerabilityStatus = "open" | "in_progress" | "resolved" | "accepted_risk";
export type ResolutionReason = "fixed" | "false_positive" | "duplicate" | "wont_fix" | "not_reproducible";
export type RegressionState = "new" | "unchanged" | "reopened" | "fixed";

// project_stats_service._UNLINKED -- the sentinel repo_scope_key for scans matching no
// connected repo. Vulnerability.repo_scope_key uses the same sentinel (see the model's
// docstring), so this is how the work queue's repo filter and "Unlinked" label recognize it.
export const UNLINKED_REPO_KEY = "__unlinked__";

export type Vulnerability = {
  id: string;
  project_id: string;
  project_repo_id: string | null;
  repo_scope_key: string;
  fingerprint: string;

  status: VulnerabilityStatus;
  resolution_reason: ResolutionReason | null;
  resolution_comment: string | null;
  resolved_by_user_id: string | null;
  resolved_by_email: string | null;
  assignee_user_id: string | null;
  assignee_email: string | null;

  current_severity: Severity | null;
  current_priority_score: number | null;
  current_priority_tier: PriorityTier | null;
  current_rule_id: string | null;
  current_rule_name: string | null;
  current_kind: FindingKind | null;
  current_message: string | null;
  current_location: FindingLocation | null;
  current_scan_id: string | null;
  latest_finding_id: string | null;

  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  reopened_at: string | null;

  // What the most recent reconciliation did with this row -- advisory only, see the model.
  last_regression_state: RegressionState | null;
  last_regression_scan_id: string | null;

  created_at: string;
  updated_at: string;
};

export type VulnerabilityScanObservation = {
  scan_id: string;
  finding_id: string;
  scan_status: ScanStatus;
  scan_type: ScanType;
  severity: Severity | null;
  created_at: string;
  completed_at: string | null;
};

export type VulnerabilityActivityEvent = {
  action: string;
  actor_type: string;
  actor_user_id: string | null;
  actor_email: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type VulnerabilityDetail = Vulnerability & {
  observations: VulnerabilityScanObservation[];
  activity: VulnerabilityActivityEvent[];
};

export type RegressionBucket = {
  /** True total for this bucket -- `items` below is only a capped preview. */
  count: number;
  items: Vulnerability[];
};

export type ScanRegressionResponse = {
  scan_id: string;
  baseline_scan_id: string | null;
  has_baseline: boolean;
  /**
   * Whether this is the newest completed scan of its repo scope. A vulnerability carries only
   * its LAST reconciliation outcome, so a superseded scan's buckets drain to zero as later
   * scans re-observe its findings — those zeros must not be rendered as "nothing changed".
   */
  is_latest_for_scope: boolean;
  new: RegressionBucket;
  unchanged: RegressionBucket;
  reopened: RegressionBucket;
  fixed: RegressionBucket;
};

export type VulnerabilityListFilters = {
  status?: VulnerabilityStatus;
  severity?: Severity;
  kind?: FindingKind;
  /** project_repo_id, or UNLINKED_REPO_KEY for the unlinked bucket. */
  repo?: string;
  assigneeUserId?: string;
  regressionState?: RegressionState;
  /** Matches rule name, message, or fingerprint. */
  search?: string;
  page?: number;
  pageSize?: number;
  sort?: string;
};

/**
 * Why a status change would be refused, or null if it's allowed.
 *
 * Mirrors the rules enforced in backend/app/routers/vulnerabilities.py so the common case is
 * caught before a round trip. It does NOT replace them — the server stays the authority and its
 * refusal message is what gets surfaced. Kept as a pure function so both the dialog and its
 * tests read the same rule rather than restating it.
 */
export function statusChangeBlockReason(
  status: VulnerabilityStatus,
  reason: ResolutionReason | null,
  comment: string
): string | null {
  if (status !== "resolved") return null;
  if (!reason) return "Pick a resolution reason.";
  // Marking something fixed by hand overrides scanner evidence, so it has to be explained.
  if (reason === "fixed" && comment.trim() === "") {
    return "A comment is required when marking a vulnerability fixed by hand.";
  }
  return null;
}

export function listVulnerabilities(projectId: string, filters: VulnerabilityListFilters = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.severity) params.set("severity", filters.severity);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.repo) params.set("repo", filters.repo);
  if (filters.assigneeUserId) params.set("assignee_user_id", filters.assigneeUserId);
  if (filters.regressionState) params.set("regression_state", filters.regressionState);
  if (filters.search) params.set("search", filters.search);
  params.set("page", String(filters.page ?? 1));
  params.set("page_size", String(filters.pageSize ?? 25));
  if (filters.sort) params.set("sort", filters.sort);
  return apiFetch<Page<Vulnerability>>(`/projects/${projectId}/vulnerabilities?${params.toString()}`);
}

export function getVulnerability(projectId: string, vulnerabilityId: string) {
  return apiFetch<VulnerabilityDetail>(`/projects/${projectId}/vulnerabilities/${vulnerabilityId}`);
}

export function updateVulnerabilityStatus(
  projectId: string,
  vulnerabilityId: string,
  payload: {
    status: VulnerabilityStatus;
    resolution_reason?: ResolutionReason | null;
    resolution_comment?: string | null;
  }
) {
  return apiFetch<Vulnerability>(`/projects/${projectId}/vulnerabilities/${vulnerabilityId}/status`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// Nullable to unassign.
export function updateVulnerabilityAssignment(
  projectId: string,
  vulnerabilityId: string,
  assigneeUserId: string | null
) {
  return apiFetch<Vulnerability>(`/projects/${projectId}/vulnerabilities/${vulnerabilityId}/assignment`, {
    method: "PATCH",
    body: JSON.stringify({ assignee_user_id: assigneeUserId }),
  });
}

export function getScanRegression(projectId: string, scanId: string) {
  return apiFetch<ScanRegressionResponse>(`/projects/${projectId}/scans/${scanId}/regression`);
}

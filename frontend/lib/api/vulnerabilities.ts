import { apiFetch } from "./client";
import type { FindingKind, FindingLocation, Severity } from "./findings";
import type { ScanStatus, ScanType } from "./scans";
import type { Page } from "./users";
import type { PriorityTier } from "@/lib/priority";
import { checkRiskComment } from "@/lib/risk-comment";

// Mirrors backend/app/models/vulnerability.py -- keep these four literal unions in lockstep
// with the Python Literal types they're read from.
export type VulnerabilityStatus = "open" | "in_progress" | "resolved" | "accepted_risk";
export type ResolutionReason = "fixed" | "false_positive" | "duplicate" | "wont_fix" | "not_reproducible";
export type RegressionState = "new" | "unchanged" | "reopened" | "fixed";
// Derived server-side (never stored): open | reopened | fixed | dismissed.
export type FixStatus = "open" | "reopened" | "fixed" | "dismissed";

// backend FindingReview (docs/FINDING_REVIEW.md): a request for a finding to stop blocking CI,
// decided by a portal admin. Only an "accepted" review exempts the finding, and only at file_path.
export type ReviewKind = "false_positive" | "accepted_risk";
export type ReviewStatus = "pending" | "accepted" | "rejected" | "revoked";
export type FindingReview = {
  kind: ReviewKind;
  status: ReviewStatus;
  file_path: string;
  requested_by_user_id: string;
  requested_by_email: string | null;
  requested_at: string;
  request_comment: string;
  reviewed_by_user_id: string | null;
  reviewed_by_email: string | null;
  reviewed_at: string | null;
  review_comment: string | null;
};

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
  review: FindingReview | null;
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

  fix_status: FixStatus;
  // Commit/branch each transition was observed in; null on legacy rows.
  first_seen_commit: string | null;
  first_seen_branch: string | null;
  first_seen_scan_id: string | null;
  last_seen_commit: string | null;
  fixed_commit: string | null;
  fixed_branch: string | null;
  fixed_scan_id: string | null;
  reopened_commit: string | null;

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

/** The merged auto-fix PR behind a fixed vulnerability (read-time join, server-side). */
export type FixedViaPullRequest = {
  pr_number: number;
  pr_url: string | null;
  pr_provider: string | null;
  merged_at: string | null;
  merge_commit: string | null;
};

export type VulnerabilityDetail = Vulnerability & {
  observations: VulnerabilityScanObservation[];
  activity: VulnerabilityActivityEvent[];
  /** Set only for a fixed vulnerability whose finding's auto-fix PR was merged. */
  fixed_via_pr: FixedViaPullRequest | null;
};

/** "Fixed via auto-fix PR #12", or null when the fix did not come through an auto-fix PR. */
export function fixedViaPrLabel(pr: FixedViaPullRequest | null | undefined): string | null {
  return pr ? `Fixed via auto-fix PR #${pr.pr_number}` : null;
}

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
  commit: string | null;
  branch: string | null;
  baseline_commit: string | null;
  baseline_branch: string | null;
  /** Baseline ran on another branch, so this scan marked nothing fixed. */
  baseline_branch_mismatch: boolean;
  scanner_version_changed: boolean;
  new: RegressionBucket;
  unchanged: RegressionBucket;
  reopened: RegressionBucket;
  fixed: RegressionBucket;
};

/** Facet counts for the current filters; each facet is counted with every OTHER filter applied. */
export type VulnerabilityFacets = {
  total: number;
  severity: Record<string, number>;
  status: Record<string, number>;
  kind: Record<string, number>;
  repo: Record<string, number>;
  review_state: Record<string, number>;
  review_kind: Record<string, number>;
  fix_status: Record<string, number>;
  age: Record<string, number>;
  rule: { id: string; name: string | null; count: number }[];
  assignee: { id: string; email: string | null; count: number }[];
};

export type BulkAction =
  | { action: "assign"; assignee_user_id: string | null }
  | {
      action: "status";
      status: VulnerabilityStatus;
      resolution_reason?: ResolutionReason | null;
      resolution_comment?: string | null;
    };

export type BulkItemResult = {
  id: string;
  ok: boolean;
  detail: string | null;
  status: string | null;
  review_status: string | null;
  assignee_user_id: string | null;
};

export type BulkResponse = { results: BulkItemResult[]; succeeded: number; failed: number };

export const BULK_MAX_IDS = 100;

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
  comment: string,
  kind: FindingKind | null = null
): string | null {
  if (status === "accepted_risk") {
    // Accepting risk has no scanner evidence behind it at all, so it needs a real justification
    // (backend validate_risk_comment: 40 chars, six words, not a placeholder).
    return checkRiskComment(comment).message;
  }
  // A published advisory against the installed version is almost never wrong.
  if (status === "resolved" && reason === "false_positive" && kind === "sca") {
    return "Dependency findings can't be marked false positive. Request accepted risk instead.";
  }
  if (status !== "resolved") return null;
  if (!reason) return "Pick a resolution reason.";
  // Marking something fixed by hand overrides scanner evidence, so it has to be explained.
  if (reason === "fixed" && comment.trim() === "") {
    return "A comment is required when marking a vulnerability fixed by hand.";
  }
  // A false-positive request goes to a portal admin, who decides from this comment alone.
  if (reason === "false_positive" && comment.trim() === "") {
    return "A comment is required when marking a vulnerability a false positive.";
  }
  return null;
}

/**
 * Whether a status change goes through the review path rather than a plain status change: a false
 * positive on a code finding, or accepted risk on any finding. Either one, once accepted, stops the
 * finding blocking CI. Whether an admin must accept first is a workspace setting per kind (the
 * server decides; read `review.status` on the response).
 */
export function needsAdminReview(
  status: VulnerabilityStatus,
  reason: ResolutionReason | null,
  kind: FindingKind | null
): boolean {
  if (status === "resolved" && reason === "false_positive") return kind !== "sca";
  return status === "accepted_risk";
}

/** `filters` are the API params from `toApiParams` (lib/vulnerability-filters). */
export function listVulnerabilities(
  projectId: string,
  filters: URLSearchParams,
  opts: { page?: number; pageSize?: number; sort?: string } = {}
) {
  const params = new URLSearchParams(filters);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 25));
  if (opts.sort) params.set("sort", opts.sort);
  return apiFetch<Page<Vulnerability>>(`/projects/${projectId}/vulnerabilities?${params.toString()}`);
}

export function getVulnerabilityFacets(projectId: string, filters: URLSearchParams) {
  const qs = filters.toString();
  return apiFetch<VulnerabilityFacets>(`/projects/${projectId}/vulnerabilities/facets${qs ? `?${qs}` : ""}`);
}

/** Up to BULK_MAX_IDS per call; a refused item reports why without stopping the rest. */
export function bulkUpdateVulnerabilities(projectId: string, ids: string[], change: BulkAction) {
  return apiFetch<BulkResponse>(`/projects/${projectId}/vulnerabilities/bulk`, {
    method: "POST",
    body: JSON.stringify({ ids, ...change }),
  });
}

/** Splits a selection into API-sized chunks. */
export function chunkIds(ids: string[], size = BULK_MAX_IDS): string[][] {
  const out: string[][] = [];
  for (let i = 0; i < ids.length; i += size) out.push(ids.slice(i, i + size));
  return out;
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

export type VulnerabilityCounts = {
  open: number;
  in_progress: number;
  reopened: number;
  fixed: number;
  dismissed: number;
};

export type VulnerabilitySummary = VulnerabilityCounts & {
  /** Keyed by project_repo_id or UNLINKED_REPO_KEY. */
  by_repo: Record<string, VulnerabilityCounts>;
};

export function getVulnerabilitySummary(projectId: string, repo?: string) {
  const qs = repo ? `?repo=${encodeURIComponent(repo)}` : "";
  return apiFetch<VulnerabilitySummary>(`/projects/${projectId}/vulnerabilities/summary${qs}`);
}

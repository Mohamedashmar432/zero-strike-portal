/**
 * AI Auto-Fix (remediation) API client. A distinct pipeline from ai.ts (analysis), but it reuses
 * the same async-job envelope (AiAnalysisResult<T>) + polling machinery. See docs/AI_AUTOFIX_DESIGN.md.
 */
import type { AiAnalysisResult } from "./ai";
import { apiFetch, apiFetchBlob } from "./client";
import type { Severity } from "./findings";

// Fine-grained lifecycle the UI drives its badges/actions off (backend AIFixProposal.review_state).
export type FixReviewState =
  | "proposed"
  | "approved"
  | "applying"
  | "validated"
  | "pr_open"
  | "manual_review"
  | "dismissed"
  | "failed";

export type FixValidation = {
  scope_ok?: boolean;
  target_cleared?: boolean;
  new_finding_count?: number;
  new_finding_fingerprints?: string[];
  baseline_count?: number;
  post_count?: number;
  scanner_version?: string | null;
  ran_at?: string;
};

export type AiFixProposal = {
  id: string;
  finding_id: string;
  scan_id: string;
  project_id: string;
  // Finding context echoed so a proposal card renders standalone.
  finding_rule_name: string | null;
  finding_severity: Severity | null;
  finding_file: string | null;
  finding_start_line: number | null;

  status: "proposed" | "applied" | "dismissed";
  review_state: FixReviewState;
  can_fix: boolean;
  confidence_score: number; // 0-100
  original_code: string | null;
  patched_code: string | null;
  unified_diff: string | null;
  explanation: string | null;
  patch_scope: string | null;
  file_path: string | null;
  risk_notes: string | null;
  manual_review_reason: string | null;

  branch_name: string | null;
  pr_url: string | null;
  pr_number: number | null;
  validation: FixValidation | null;
  created_at: string;
  updated_at: string;
};

export type AutoFixSummary = {
  total_findings: number;
  auto_fixable: number;
  manual_review: number;
  proposed: number;
  approved: number;
  applied: number;
  pr_created: number;
  dismissed: number;
  failed: number;
};

export type AutoFixInsight = { summary: AutoFixSummary; proposals: AiFixProposal[] };

// Scan-level generation job: the AI async envelope, insight = summary + proposals.
export type ScanAutoFixJob = AiAnalysisResult<AutoFixInsight>;
export type FindingAutoFixJob = AiAnalysisResult<AiFixProposal>;

export function getScanAutoFix(scanId: string) {
  return apiFetch<ScanAutoFixJob>(`/scans/${scanId}/auto-fix`);
}

export function triggerScanAutoFix(scanId: string, body: { force?: boolean; finding_ids?: string[] } = {}) {
  return apiFetch<ScanAutoFixJob>(`/scans/${scanId}/auto-fix`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getFindingAutoFix(findingId: string) {
  return apiFetch<FindingAutoFixJob>(`/findings/${findingId}/auto-fix`);
}

export function triggerFindingAutoFix(findingId: string, body: { force?: boolean } = {}) {
  return apiFetch<FindingAutoFixJob>(`/findings/${findingId}/auto-fix`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getFixProposal(proposalId: string) {
  return apiFetch<AiFixProposal>(`/fix-proposals/${proposalId}`);
}

// Approve = create branch + open PR (owner/admin only, backend-enforced). Async; poll to see pr_url.
export function approveFixProposal(proposalId: string, body: { branch_name?: string } = {}) {
  return apiFetch<AiFixProposal>(`/fix-proposals/${proposalId}/approve`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function dismissFixProposal(proposalId: string, body: { reason?: string } = {}) {
  return apiFetch<AiFixProposal>(`/fix-proposals/${proposalId}/dismiss`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function downloadFixPatch(proposalId: string) {
  return apiFetchBlob(`/fix-proposals/${proposalId}/patch`);
}

/**
 * AI Auto-Fix (remediation) API client. A distinct pipeline from ai.ts (analysis), but it reuses
 * the same async-job envelope (AiAnalysisResult<T>) + polling machinery. See docs/AI_AUTOFIX_DESIGN.md.
 */
import type { AiAnalysisResult, AiAnalysisStatus } from "./ai";
import { apiFetch, apiFetchBlob } from "./client";
import type { Severity } from "./findings";
import type { ScanType } from "./scans";

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

// SCA version-bump picker context (scanner data only). Present on SCA-finding proposals.
export type DependencyUpdate = {
  package: string | null;
  ecosystem: string | null;
  current_version: string | null;
  available_versions: string[];
  recommended_version: string | null;
  manifest: string | null;
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
  dependency_update: DependencyUpdate | null;
  manual_review_reason: string | null;

  branch_name: string | null;
  pr_url: string | null;
  pr_number: number | null;
  validation: FixValidation | null;
  created_at: string;
  updated_at: string;
};

export type AutoFixRiskRating = "none" | "low" | "medium" | "high" | "critical";

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
  // 3-way breakdown (can_fix x confidence threshold) rendered on the report page.
  ai_fixable: number; // AI can fix (confident)
  needs_review_on_fix: number; // AI proposed a fix but a human should review it (low confidence)
  cannot_fix: number; // AI couldn't produce a safe fix — manual remediation
  risk_rating: AutoFixRiskRating;
};

export type AutoFixInsight = { summary: AutoFixSummary; proposals: AiFixProposal[] };

// One row in the dedicated Auto-Fix section list.
export type ProjectAutoFixScanItem = {
  scan_id: string;
  project_repo_id: string | null;
  repo_url: string | null;
  scan_label: string | null;
  scan_type: ScanType | null;
  branch: string | null;
  scan_created_at: string | null;
  status: AiAnalysisStatus;
  started_at: string | null;
  progress_completed: number;
  progress_total: number;
  summary: AutoFixSummary;
};

export type ProjectAutoFixListResponse = { items: ProjectAutoFixScanItem[] };

export function listProjectAutoFix(projectId: string) {
  return apiFetch<ProjectAutoFixListResponse>(`/projects/${projectId}/auto-fix/scans`);
}

// --- admin-only Auto-Fix policy (RemediationSettings singleton) ---

export type RemediationSettings = {
  enabled: boolean;
  confidence_threshold: number; // 0-100
  max_findings_per_job: number;
  blocking_severities: string[]; // subset of critical/high/medium/low/info
};

export function getRemediationSettings() {
  return apiFetch<RemediationSettings>("/remediation-settings/settings");
}

export function updateRemediationSettings(body: Partial<RemediationSettings>) {
  return apiFetch<RemediationSettings>("/remediation-settings/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

// --- team controls: per-finding comments + activity timeline ---

export type FindingComment = {
  id: string;
  finding_id: string;
  author_user_id: string;
  author_name: string | null;
  author_email: string | null;
  body: string;
  created_at: string;
};

export function listFindingComments(findingId: string) {
  return apiFetch<{ items: FindingComment[] }>(`/findings/${findingId}/comments`);
}

export function addFindingComment(findingId: string, body: { body: string }) {
  return apiFetch<FindingComment>(`/findings/${findingId}/comments`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export type CommentSummary = { total: number; by_finding: { finding_id: string; count: number }[] };

export function getScanCommentSummary(scanId: string) {
  return apiFetch<CommentSummary>(`/scans/${scanId}/comments/summary`);
}

export type ActivityEvent = {
  action: string;
  actor_user_id: string | null;
  actor_name: string | null;
  target_type: string | null;
  target_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export function getScanAutoFixActivity(scanId: string) {
  return apiFetch<{ items: ActivityEvent[] }>(`/scans/${scanId}/auto-fix/activity`);
}

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

// --- per-fix Ask-AI Q&A + "change it" revise ---

export type FixConversationMessage = {
  role: "user" | "assistant";
  body: string;
  author_user_id: string | null;
  kind: "qa" | "revision";
  created_at: string;
};

export type FixConversation = { proposal_id: string; messages: FixConversationMessage[] };

export function getFixConversation(proposalId: string) {
  return apiFetch<FixConversation>(`/fix-proposals/${proposalId}/conversation`);
}

// Read-only Q&A about the fix; returns the updated conversation (question + AI answer appended).
export function askFixProposal(proposalId: string, body: { question: string }) {
  return apiFetch<FixConversation>(`/fix-proposals/${proposalId}/ask`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// "Change the fix to X" — re-runs the fix agent with the instruction; async, poll the finding job.
export function reviseFixProposal(proposalId: string, body: { instruction: string }) {
  return apiFetch<FindingAutoFixJob>(`/fix-proposals/${proposalId}/revise`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

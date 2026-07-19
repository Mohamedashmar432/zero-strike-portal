import { apiFetch } from "./client";
import type { Severity } from "./findings";

/**
 * Exact list the backend accepts for `provider` on `AiProviderConfig.provider` (the provider
 * config form) and the raw `FindingInsight.provider`/`ScanInsight.provider` fields. Keep in
 * sync with the backend contract -- do not add providers (e.g. azure_openai) speculatively.
 */
export type AiProvider =
  | "anthropic"
  | "openai"
  | "lmstudio"
  | "kimi"
  | "nvidia_nim"
  | "openrouter"
  | "custom"
  | "commandcode"
  | "groq";

export type AiStatus = { enabled: boolean };

export type AiProviderConfig = {
  id: string;
  name: string;
  provider: AiProvider;
  model_name: string | null;
  base_url: string | null;
  temperature: number;
  is_active: boolean;
  // The raw/encrypted API key is never returned -- this is the only signal any UI gets
  // about whether one is already configured server-side.
  has_api_key: boolean;
  total_requests: number;
  total_failed_requests: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost_usd: number;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
  updated_by: string | null;
};

export type CreateAiProviderInput = {
  name: string;
  provider: AiProvider;
  model_name: string;
  base_url?: string;
  // Required on create -- there's no existing key to fall back to.
  api_key: string;
  temperature?: number;
};

export type UpdateAiProviderInput = {
  name: string;
  provider: AiProvider;
  model_name: string;
  base_url?: string;
  // Omitted (not just empty-string) means "keep the existing key".
  api_key?: string;
  clear_api_key?: boolean;
  temperature?: number;
};

export type TestAiProviderInput = {
  // Present for a saved row (reuses its stored key server-side); absent for a draft, in
  // which case api_key must be supplied.
  id?: string;
  provider: AiProvider;
  model_name: string;
  api_key?: string;
  base_url?: string;
  temperature?: number;
};

export type AiAnalysisStatus = "not_requested" | "queued" | "in_progress" | "completed" | "failed";

export type AiAnalysisResult<T> = {
  status: AiAnalysisStatus;
  error_message: string | null;
  // While queued/in_progress: when it started + batch progress (completed/total), for the
  // "AI analyzing · N% · ~Xs left" tag. progress_total is 0 until the batch count is known.
  started_at: string | null;
  progress_completed: number;
  progress_total: number;
  insight: T | null;
};

export type FindingInsight = {
  is_false_positive: boolean | null;
  false_positive_confidence: number | null;
  // The AI's confidence in its own verdict (0-1) — shown as "AI confidence". Distinct from
  // false_positive_confidence (which is ~0 for genuine findings and was being mislabeled as this).
  analysis_confidence: number | null;
  verdict_reasoning: string | null;
  improved_description: string | null;
  // How many other findings share this rule (same vuln recurring across the repo). >0 => show the
  // "found in N other locations" tag.
  similar_finding_count: number;
  // Display-only AI severity overlay (null when the AI left the scanner severity as-is).
  adjusted_severity: Severity | null;
  severity_reasoning: string | null;
  owasp: string[];
  cwe: string[];
  cvss_score: number | null;
  explanation: string | null;
  provider: string;
  model_name: string;
  updated_at: string;
};

export type ScanInsight = {
  summary: string | null;
  // How many findings the job set out to analyze; when > total_findings_analyzed, coverage was
  // partial (the summary spells out "Analyzed X of Y" and a re-run backfills the rest).
  total_findings_intended: number | null;
  total_findings_analyzed: number | null;
  false_positive_count: number | null;
  top_recommendations: string[];
  provider: string;
  model_name: string;
  updated_at: string;
};

export function getAiStatus() {
  return apiFetch<AiStatus>("/ai/status");
}

export function listAiProviders() {
  return apiFetch<AiProviderConfig[]>("/ai/providers");
}

export function createAiProvider(input: CreateAiProviderInput) {
  return apiFetch<AiProviderConfig>("/ai/providers", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateAiProvider(id: string, input: UpdateAiProviderInput) {
  return apiFetch<AiProviderConfig>(`/ai/providers/${id}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function deleteAiProvider(id: string) {
  return apiFetch<void>(`/ai/providers/${id}`, { method: "DELETE" });
}

export function activateAiProvider(id: string) {
  return apiFetch<AiProviderConfig[]>(`/ai/providers/${id}/activate`, { method: "POST" });
}

export function deactivateAiProvider() {
  return apiFetch<AiProviderConfig[]>("/ai/providers/deactivate", { method: "POST" });
}

export function testAiProviderConnection(input: TestAiProviderInput) {
  if (input.id) {
    return apiFetch<void>(`/ai/providers/${input.id}/test`, { method: "POST" });
  }
  return apiFetch<void>("/ai/providers/test", {
    method: "POST",
    body: JSON.stringify({
      provider: input.provider,
      model_name: input.model_name,
      api_key: input.api_key,
      base_url: input.base_url,
      temperature: input.temperature,
    }),
  });
}

export function getFindingAnalysis(findingId: string) {
  return apiFetch<AiAnalysisResult<FindingInsight>>(`/findings/${findingId}/ai-analysis`);
}

export function triggerFindingAnalysis(findingId: string, opts: { force?: boolean } = {}) {
  return apiFetch<AiAnalysisResult<FindingInsight>>(`/findings/${findingId}/ai-analysis`, {
    method: "POST",
    body: JSON.stringify(opts),
  });
}

export function getScanAnalysis(scanId: string) {
  return apiFetch<AiAnalysisResult<ScanInsight>>(`/scans/${scanId}/ai-analysis`);
}

export function triggerScanAnalysis(scanId: string, opts: { force?: boolean } = {}) {
  return apiFetch<AiAnalysisResult<ScanInsight>>(`/scans/${scanId}/ai-analysis`, {
    method: "POST",
    body: JSON.stringify(opts),
  });
}

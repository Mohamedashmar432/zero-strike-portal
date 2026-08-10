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
  | "groq"
  | "gemini";

export type AiStatus = { enabled: boolean };

export type AiProviderConfig = {
  id: string;
  name: string;
  // null = the portal-wide provider an admin manages; set = this project's own key (BYOK).
  project_id: string | null;
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

export type ProjectAiUsage = {
  enabled: boolean;
  active_provider: string | null;
  active_model: string | null;
  total_requests: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost_usd: number;
};

/** Workspace-wide AI policy. Only the "Project BYOK" switch for now. */
export type AiSettings = { project_byok_enabled: boolean };

/**
 * One row per LLM call. Metadata only, deliberately — prompts carry customer source and
 * findings, so they are never stored or returned.
 */
export type AiUsageEvent = {
  id: string;
  created_at: string;
  project_id: string | null;
  project_name: string | null;
  scan_id: string | null;
  scope: "project" | "portal";
  feature: string;
  provider: string;
  model_name: string | null;
  status: "success" | "failed";
  error_type: string | null;
  duration_ms: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
};

export type AiUsageTotals = {
  requests: number;
  failed: number;
  /** Percent, 0-100. An empty window reads 100 — "no calls" is not "every call failed". */
  success_rate: number;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  avg_duration_ms: number;
};

/**
 * Same shape at both scopes — `by_project` is simply empty for a single project. That's what
 * lets one dashboard component render the project tab and the admin page.
 */
export type AiAnalytics = {
  days: number;
  totals: AiUsageTotals;
  timeseries: (Omit<AiUsageTotals, "avg_duration_ms"> & { date: string })[];
  by_feature: (AiUsageTotals & { feature: string })[];
  by_model: (AiUsageTotals & { provider: string; model_name: string | null })[];
  by_project: (AiUsageTotals & { project_id: string | null; project_name: string })[];
};

export type AiUsageEventPage = {
  items: AiUsageEvent[];
  total: number;
  page: number;
  page_size: number;
};

export type AiEventFilters = {
  days?: number;
  page?: number;
  page_size?: number;
  feature?: string;
  status?: "success" | "failed";
  project_id?: string;
};

function eventQuery(filters: AiEventFilters) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

/**
 * Pass `projectId` from any project-scoped screen. Under Project BYOK the answer differs per
 * project, and asking without one reports AI as unavailable for everybody.
 */
export function getAiStatus(projectId?: string) {
  return apiFetch<AiStatus>(projectId ? `/ai/status?project_id=${projectId}` : "/ai/status");
}

export function getAiSettings() {
  return apiFetch<AiSettings>("/ai/settings");
}

export function updateAiSettings(input: AiSettings) {
  return apiFetch<AiSettings>("/ai/settings", { method: "PUT", body: JSON.stringify(input) });
}

// --- per-project provider (BYOK) ---------------------------------------------------------

export function listProjectAiProviders(projectId: string) {
  return apiFetch<AiProviderConfig[]>(`/projects/${projectId}/ai-provider`);
}

export function createProjectAiProvider(projectId: string, input: CreateAiProviderInput) {
  return apiFetch<AiProviderConfig>(`/projects/${projectId}/ai-provider`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateProjectAiProvider(
  projectId: string,
  configId: string,
  input: UpdateAiProviderInput,
) {
  return apiFetch<AiProviderConfig>(`/projects/${projectId}/ai-provider/${configId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function deleteProjectAiProvider(projectId: string, configId: string) {
  return apiFetch<void>(`/projects/${projectId}/ai-provider/${configId}`, { method: "DELETE" });
}

export function activateProjectAiProvider(projectId: string, configId: string) {
  return apiFetch<AiProviderConfig[]>(`/projects/${projectId}/ai-provider/${configId}/activate`, {
    method: "POST",
  });
}

export function testProjectAiProvider(projectId: string, configId: string) {
  return apiFetch<void>(`/projects/${projectId}/ai-provider/${configId}/test`, { method: "POST" });
}

// --- usage analytics ----------------------------------------------------------------------

export function getProjectAiAnalytics(projectId: string, days = 30) {
  return apiFetch<AiAnalytics>(`/projects/${projectId}/ai-analytics?days=${days}`);
}

export function listProjectAiEvents(projectId: string, filters: AiEventFilters = {}) {
  return apiFetch<AiUsageEventPage>(`/projects/${projectId}/ai-events${eventQuery(filters)}`);
}

export function getPortalAiAnalytics(days = 30, projectId?: string) {
  const scope = projectId ? `&project_id=${projectId}` : "";
  return apiFetch<AiAnalytics>(`/admin/ai-analytics?days=${days}${scope}`);
}

export function listPortalAiEvents(filters: AiEventFilters = {}) {
  return apiFetch<AiUsageEventPage>(`/admin/ai-analytics/events${eventQuery(filters)}`);
}

export function getProjectAiUsage(projectId: string) {
  return apiFetch<ProjectAiUsage>(`/projects/${projectId}/ai-usage`);
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

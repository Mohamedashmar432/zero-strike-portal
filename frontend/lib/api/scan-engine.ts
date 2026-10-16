import { apiFetch } from "./client";

export type RuleState = "active" | "retired" | "custom";

export type RuleRow = {
  rule_id: string;
  title: string | null;
  severity: string | null;
  language: string | null;
  total_findings: number;
  fp_tags: number;
  fp_rate: number; // 0..1
  projects_affected: number;
  state: RuleState;
  noisy: boolean;
  pending: boolean;
  retire_reason: string | null;
};

export type RuleStats = {
  rules: RuleRow[];
  noisy_min_fp_tags: number;
  noisy_min_fp_percent: number;
  active_version: number | null;
};

export type FpTag = {
  project_id: string;
  project_name: string;
  tagged_at: string | null;
  tagged_by: string | null;
  comment: string | null;
};

export type CustomRule = {
  rule_id: string;
  language: string;
  yaml: string;
  vulnerable_sample: string;
  safe_sample: string;
  last_validated_at: string;
  created_by: string;
};

export type PendingChanges = {
  retired: string[];
  restored: string[];
  custom_added: string[];
  custom_edited: string[];
  custom_removed: string[];
};

export type PackVersion = {
  version: number;
  changelog: string;
  published_by: string;
  published_at: string;
  rolled_back_from: number | null;
  retired_count: number;
  custom_count: number;
};

const BASE = "/admin/scan-engine";
const post = (path: string, body?: unknown) =>
  apiFetch(`${BASE}${path}`, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const fpRateLabel = (rate: number) => `${Math.round(rate * 100)}%`;

export const hasPendingChanges = (p: PendingChanges | undefined) =>
  !!p && Object.values(p).some((list) => list.length > 0);

export const getRules = () => apiFetch<RuleStats>(`${BASE}/rules`);
export const getRuleHistory = (ruleId: string) =>
  apiFetch<{ rule_id: string; fp_tags: FpTag[] }>(`${BASE}/rules/${encodeURIComponent(ruleId)}/history`);
export const retireRule = (ruleId: string, reason: string) =>
  post(`/rules/${encodeURIComponent(ruleId)}/retire`, { reason });
export const restoreRule = (ruleId: string) => post(`/rules/${encodeURIComponent(ruleId)}/restore`);
export const setThresholds = (minFpTags: number, minFpPercent: number) =>
  apiFetch(`${BASE}/thresholds`, {
    method: "PUT",
    body: JSON.stringify({ min_fp_tags: minFpTags, min_fp_percent: minFpPercent }),
  });

export const getCustomRules = () => apiFetch<CustomRule[]>(`${BASE}/custom-rules`);
export const saveCustomRule = (body: { yaml: string; vulnerable_sample: string; safe_sample: string }) =>
  post("/custom-rules", body);
export const deleteCustomRule = (ruleId: string) =>
  apiFetch(`${BASE}/custom-rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" });

export const getPending = () => apiFetch<PendingChanges>(`${BASE}/pending`);
export const getVersions = () => apiFetch<PackVersion[]>(`${BASE}/versions`);
export const publishVersion = (changelog: string) => post("/versions", { changelog });
export const rollBackVersion = (version: number, changelog?: string) =>
  post(`/versions/${version}/rollback`, { changelog: changelog || null });

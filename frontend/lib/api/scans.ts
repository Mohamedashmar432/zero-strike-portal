import { apiFetch } from "./client";
import type { Page } from "./users";

export type ScanType = "local" | "cloud" | "cicd";
export type ScanStatus = "pending" | "running" | "completed" | "failed";
export type CiProvider = "github_actions" | "gitlab_ci" | "azure_pipelines";

export type Scan = {
  id: string;
  project_id: string;
  scan_type: ScanType;
  triggered_by: "cli" | "ci" | "cloud" | "manual";
  status: ScanStatus;
  api_key_id: string | null;
  scanner_version: string | null;
  hostname: string | null;
  git_commit: string | null;
  branch: string | null;
  scan_label: string | null;
  repo_url: string | null;
  ci_provider: CiProvider | null;
  created_by: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export function listScans(projectId: string, page = 1, pageSize = 20) {
  return apiFetch<Page<Scan>>(`/projects/${projectId}/scans?page=${page}&page_size=${pageSize}`);
}

export function createScan(
  projectId: string,
  input: { scan_type: ScanType; scan_label?: string; repo_url?: string; ci_provider?: CiProvider }
) {
  return apiFetch<Scan>(`/projects/${projectId}/scans`, { method: "POST", body: JSON.stringify(input) });
}

export function getScan(id: string) {
  return apiFetch<Scan>(`/scans/${id}`);
}

export function mockCompleteScan(id: string, status: "completed" | "failed" = "completed", errorMessage?: string) {
  return apiFetch<Scan>(`/scans/${id}/_mock-complete`, {
    method: "POST",
    body: JSON.stringify({ status, error_message: errorMessage }),
  });
}

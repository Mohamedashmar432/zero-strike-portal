import { apiFetch } from "./client";
import type { Page } from "./users";

export type ScanType = "local" | "cloud" | "cicd";
export type ScanStatus = "pending" | "queued" | "running" | "completed" | "failed";
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
  project_repo_id: string | null;
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

// Only cloud scans are created via the API — local/CI scans are created by the
// scanner itself (POST /api/v1/scans, api-key auth) after the user runs the CLI.
export function createCloudScan(
  projectId: string,
  input: {
    repo_url?: string;
    branch?: string;
    scan_label?: string;
    repo_token?: string;
    connection_id?: string;
    project_repo_id?: string;
  }
) {
  return apiFetch<Scan>(`/projects/${projectId}/scans`, {
    method: "POST",
    body: JSON.stringify({ scan_type: "cloud", ...input }),
  });
}

export function getScan(id: string) {
  return apiFetch<Scan>(`/scans/${id}`);
}

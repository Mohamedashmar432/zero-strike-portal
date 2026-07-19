import { apiFetch } from "./client";
import type { SeverityCounts } from "./dashboard";
import type { ScanStatus, ScanType } from "./scans";
import type { Page } from "./users";

export type ScanStatusCounts = Record<ScanStatus, number>;

export type ProjectStatsItem = {
  project_id: string;
  total_findings: number;
  findings_by_severity: SeverityCounts;
  scan_status_counts: ScanStatusCounts;
  risk_repo_count: number;
  total_repo_count: number;
};

export type Project = {
  id: string;
  name: string;
  description: string | null;
  owner_id: string;
  is_archived: boolean;
  scan_count: number;
  last_scan_at: string | null;
  report_template: "standard" | "executive" | null;
  created_at: string;
  updated_at: string;
  my_role: "owner" | "collaborator" | "admin";
  // Only populated on getProject() — see backend ProjectResponse docstring.
  total_findings: number | null;
  findings_by_severity: SeverityCounts | null;
  scan_status_counts: ScanStatusCounts | null;
  risk_repo_count: number | null;
  total_repo_count: number | null;
};

export type ScanHistoryItem = {
  scan_id: string;
  status: ScanStatus;
  created_at: string;
  completed_at: string | null;
  total_findings: number;
  findings_by_severity: SeverityCounts;
  // Populated by scan-activity: scan kind + who/what started it (member name, CI provider, host).
  scan_type: ScanType | null;
  scanned_by: string | null;
};

export type OwaspSummary = {
  project_id: string;
  project_repo_id: string | null;
  by_owasp: Record<string, number>;
};

export type RepoScanGroup = {
  repo_id: string | null; // null = the synthetic "Unlinked scans" group
  repo_label: string;
  provider: string | null;
  scans: ScanHistoryItem[]; // newest -> oldest
};

export type ProjectScanActivity = {
  repos: RepoScanGroup[];
  // Live posture: sum of each repo's most recent completed scan (not the all-time total).
  current_findings: SeverityCounts;
  current_findings_total: number;
};

export function listProjects(page = 1, pageSize = 20) {
  return apiFetch<Page<Project>>(`/projects?page=${page}&page_size=${pageSize}`);
}

// Batched — one call for the whole projects list table, avoids N+1 per-row stat fetches.
export function getProjectsStats() {
  return apiFetch<{ items: Record<string, ProjectStatsItem> }>("/projects/stats");
}

export function getProject(id: string) {
  return apiFetch<Project>(`/projects/${id}`);
}

export function getRepoScanHistory(projectId: string, repoId: string, limit = 30) {
  return apiFetch<ScanHistoryItem[]>(`/projects/${projectId}/repos/${repoId}/scan-history?limit=${limit}`);
}

export function getProjectScanActivity(projectId: string) {
  return apiFetch<ProjectScanActivity>(`/projects/${projectId}/scan-activity`);
}

export function getProjectOwaspSummary(projectId: string, projectRepoId?: string) {
  const params = projectRepoId ? `?project_repo_id=${encodeURIComponent(projectRepoId)}` : "";
  return apiFetch<OwaspSummary>(`/projects/${projectId}/owasp-summary${params}`);
}

export function createProject(input: { name: string; description?: string }) {
  return apiFetch<Project>("/projects", { method: "POST", body: JSON.stringify(input) });
}

export function updateProject(
  id: string,
  patch: {
    name?: string;
    description?: string;
    is_archived?: boolean;
    report_template?: "inherit" | "standard" | "executive";
  }
) {
  return apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
}

export function deleteProject(id: string) {
  return apiFetch<void>(`/projects/${id}`, { method: "DELETE" });
}

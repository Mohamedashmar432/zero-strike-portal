import type { AiAnalysisStatus } from "./ai";
import { apiFetch } from "./client";

export type SeverityCounts = {
  critical: number;
  high: number;
  medium: number;
  low: number;
  info: number;
};

export type RecentScanItem = {
  scan_id: string;
  project_id: string;
  project_name: string;
  status: "pending" | "queued" | "running" | "completed" | "failed";
  scan_type: "local" | "cloud" | "cicd";
  created_at: string;
  findings_by_severity: SeverityCounts;
  ai_analysis_status: AiAnalysisStatus | null;
  ai_analysis_started_at: string | null;
  ai_analysis_progress_completed: number;
  ai_analysis_progress_total: number;
};

/** How much of the workspace the current-exposure number actually saw. */
export type PostureCoverage = {
  repos_scanned: number;
  repos_without_completed_scan: number;
  has_unlinked_scans: boolean;
};

export type DashboardStats = {
  project_count: number;
  /** Historical volume — every scan ever run, not current exposure. */
  scan_count: number;
  /** Current exposure: the latest completed scan per repository, never the all-time sum. */
  findings_by_severity: SeverityCounts;
  posture_coverage: PostureCoverage;
  recent_scans: RecentScanItem[];
};

export function getDashboardStats() {
  return apiFetch<DashboardStats>("/dashboard/stats");
}

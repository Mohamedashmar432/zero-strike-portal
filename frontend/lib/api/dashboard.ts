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

export type DashboardStats = {
  project_count: number;
  scan_count: number;
  findings_by_severity: SeverityCounts;
  recent_scans: RecentScanItem[];
};

export function getDashboardStats() {
  return apiFetch<DashboardStats>("/dashboard/stats");
}

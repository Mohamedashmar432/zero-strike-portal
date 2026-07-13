import { apiFetch } from "./client";

export type DashboardStats = {
  project_count: number;
  scan_count: number;
  findings_by_severity: {
    critical: number;
    high: number;
    medium: number;
    low: number;
    info: number;
  };
};

export function getDashboardStats() {
  return apiFetch<DashboardStats>("/dashboard/stats");
}

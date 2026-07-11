import { apiFetch, apiFetchBlob } from "./client";

export type ReportStats = {
  files_scanned: number | null;
  files_skipped: number | null;
  files_cached: number | null;
  total_findings: number | null;
  suppressed: number | null;
  by_severity: Record<string, number>;
  by_language: Record<string, number>;
  by_category: Record<string, number>;
  by_kind: Record<string, number>;
};

export type Report = {
  scan_id: string;
  project_id: string;
  scanner_scan_id: string | null;
  scanner_version: string | null;
  started_at: string | null;
  duration_ms: number | null;
  root_path: string | null;
  git_commit: string | null;
  branch: string | null;
  hostname: string | null;
  stats: ReportStats;
  diagnostics: { severity: string | null; message: string | null; location: string | null }[];
  html_available: boolean;
  generated_at: string;
};

export function getReport(scanId: string) {
  return apiFetch<Report>(`/scans/${scanId}/report`);
}

export function downloadReportPdf(scanId: string) {
  return apiFetchBlob(`/scans/${scanId}/report/pdf`);
}

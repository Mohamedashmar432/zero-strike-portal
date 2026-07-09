import { apiFetch } from "./client";
import { getTokens } from "./token-store";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

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

// Download endpoints are JWT-gated, so a plain <a href> (no auth header) won't work —
// fetch the bytes with the access token and return a Blob for a client-side download.
export async function downloadReport(scanId: string, fmt: "json" | "html"): Promise<Blob> {
  const { accessToken } = getTokens();
  const res = await fetch(`${API_BASE_URL}/scans/${scanId}/report/download/${fmt}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  return res.blob();
}

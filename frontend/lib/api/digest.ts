import { apiFetch } from "./client";

export type DigestSettings = {
  enabled: boolean;
  frequency: "daily" | "weekly";
  hour_utc: number;
  minute_utc: number;
  /** 0 = Monday. Weekly only. */
  weekday: number;
  project_ids: string[];
  include_stale_projects: boolean;
  last_sent_at: string | null;
  last_status: string | null;
  last_error: string | null;
};

export type DigestNumbers = {
  pipeline_runs: number;
  pipeline_failed: number;
  cloud_scans: number;
  cloud_failed: number;
  critical: number;
  high: number;
};

export type DigestRow = DigestNumbers & {
  project_id: string;
  name: string;
  /** All-time, over every repo of the project. */
  resolved: number;
  /** Vulnerabilities first seen in the period. */
  new_findings: number;
  false_positives: number;
  vulnerabilities: number;
};

export type OutdatedPipeline = {
  project_id: string;
  project: string;
  repository: string;
  scanner_version: string;
  runs: number;
  last_run_at: string | null;
};

export type DigestPreview = {
  period_start: string;
  period_end: string;
  rows: DigestRow[];
  totals: DigestNumbers;
  scanner: {
    engine_available: boolean;
    backend_scanner_version: string | null;
    latest_binary_version: string | null;
    projects_outdated: number;
    /** CI/CD scans in the period on a scanner other than the latest binary; oldest version first. */
    outdated_pipelines: OutdatedPipeline[];
    new_advisory_count: number;
  };
  stale_projects: { project_id: string; name: string; last_scan_at: string | null }[];
  quota_warnings: { project_id: string; name: string; used: number; limit: number }[];
};

export type DigestSendResult = {
  sent: number;
  cards: number;
  errors: { channel_id: string; name: string; error: string }[];
};

export const getDigestSettings = () => apiFetch<DigestSettings>("/admin/digest-settings");

export const saveDigestSettings = (body: Omit<DigestSettings, "last_sent_at" | "last_status" | "last_error">) =>
  apiFetch<DigestSettings>("/admin/digest-settings", { method: "PUT", body: JSON.stringify(body) });

export const getDigestPreview = () => apiFetch<DigestPreview>("/admin/digest-settings/preview");

export const sendDigestTest = () =>
  apiFetch<DigestSendResult>("/admin/digest-settings/send-test", { method: "POST" });

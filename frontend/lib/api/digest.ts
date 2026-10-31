import { apiFetch } from "./client";
import type { NewCves } from "./project-insights";

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
  quota_used: number;
  quota_limit: number;
};

export type DigestRow = DigestNumbers & {
  project_id: string;
  name: string;
  new_cves: NewCves;
};

export type DigestPreview = {
  period_start: string;
  period_end: string;
  rows: DigestRow[];
  totals: DigestNumbers & { new_cves?: NewCves };
  scanner: {
    engine_available: boolean;
    backend_scanner_version: string | null;
    latest_binary_version: string | null;
    outdated_ci_runners: number;
    rule_pack_version: string | null;
    rule_count: number | null;
    osv_reachable: boolean;
    // Round-trip of each OSV.dev endpoint the scanner calls; null = unreachable.
    osv_batch_ms: number | null;
    osv_vuln_ms: number | null;
    osv_checked_at: string | null;
    last_dependency_scan_at: string | null;
    new_cve_ids: string[];
    new_advisories: { id: string; severity: string; projects: number }[];
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

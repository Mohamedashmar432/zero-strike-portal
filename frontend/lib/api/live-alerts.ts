import { apiFetch } from "./client";

export type LiveAlertMinSeverity = "critical" | "high" | "medium";
export type LiveAlertSeverity = "critical" | "high" | "medium" | "low";

export interface LiveAlertLocation {
  repo_label: string;
  manifests: string[];
  inventory_scanned_at: string | null;
  git_commit: string | null;
}

export interface LiveAlertDelivery {
  /** Webhook channels the event matched (not a delivery outcome). */
  channels: number;
  /** In-app notifications written. */
  in_app: number;
  project_webhook: "sent" | "failed" | "off";
  project_email: "sent" | "failed" | "not_configured" | "off";
}

export interface LiveAlertRow {
  id: string;
  project_id: string;
  /** null when the project no longer exists. */
  project_name: string | null;
  advisory_id: string;
  advisory_ids: string[];
  summary: string;
  ecosystem: string;
  package: string;
  version: string;
  severity: LiveAlertSeverity;
  cvss_score: number | null;
  malicious: boolean;
  published_at: string;
  fixed_versions: string[];
  locations: LiveAlertLocation[];
  created_at: string;
  delivery: LiveAlertDelivery;
}

export interface EcosystemLag {
  ecosystem: string;
  /** null until the first run has recorded the feed head. */
  cursor: string | null;
  lag_minutes: number | null;
}

export interface InventoryCoverage {
  projects_active: number;
  projects_with_inventory: number;
  inventories_cloud: number;
  inventories_cicd: number;
  oldest_inventory_at: string | null;
}

export interface LiveAlertStatus {
  enabled: boolean;
  min_severity: LiveAlertMinSeverity;
  include_malicious: boolean;
  /** True means ADVISORY_WATCH_ENABLED=true in the environment (the watcher may run). */
  server_watch_enabled: boolean;
  interval_minutes: number;
  max_age_hours: number;
  last_run_started_at: string | null;
  last_run_finished_at: string | null;
  last_success_at: string | null;
  last_status: "ok" | "partial" | "error" | null;
  last_error: string | null;
  consecutive_failures: number;
  failing_since: string | null;
  last_gap_at: string | null;
  last_gap_hours: number | null;
  ecosystems: EcosystemLag[];
  last_advisory_id: string | null;
  last_advisory_published_at: string | null;
  last_run_summary: Record<string, unknown>;
  coverage: InventoryCoverage;
  email_delivery_configured: boolean;
  recent: LiveAlertRow[];
}

export interface LiveAlertSettingsUpdate {
  enabled?: boolean;
  min_severity?: LiveAlertMinSeverity;
  include_malicious?: boolean;
}

export interface RunPreview {
  project_id: string;
  project_name: string;
  /** The Adaptive Card exactly as it would be posted. */
  card: Record<string, unknown>;
  bytes: number;
}

export interface LiveAlertRunResponse {
  status: "ran" | "busy" | "skipped";
  dry_run: boolean;
  summary: Record<string, unknown>;
  previews: RunPreview[];
}

export interface ProjectInventory {
  repo_label: string;
  scan_type: string;
  scanned_at: string;
  git_commit: string | null;
  dep_count: number;
  scanner_version: string | null;
  truncated: boolean;
}

export interface ProjectLiveAlerts {
  effective_min_severity: "critical" | "high" | "medium" | "off";
  enabled: boolean;
  inventories: ProjectInventory[];
  alerts: LiveAlertRow[];
  email_delivery_configured: boolean;
}

export const getLiveAlertStatus = () => apiFetch<LiveAlertStatus>("/admin/live-alerts");
export const saveLiveAlertSettings = (body: LiveAlertSettingsUpdate) =>
  apiFetch<LiveAlertStatus>("/admin/live-alerts", { method: "PUT", body: JSON.stringify(body) });
export const runLiveAlertCheck = (dryRun: boolean) =>
  apiFetch<LiveAlertRunResponse>(`/admin/live-alerts/run?dry_run=${dryRun ? "true" : "false"}`, { method: "POST" });
export const getProjectLiveAlerts = (projectId: string) =>
  apiFetch<ProjectLiveAlerts>(`/projects/${projectId}/live-alerts`);

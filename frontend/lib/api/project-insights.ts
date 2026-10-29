import { apiFetch } from "./client";
import type { CloudScanQuota } from "./projects";
import type { ScanStage, ScanStatus, ScanType } from "./scans";

// See docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md.
export type ScanCounts = { total: number; completed: number; failed: number; active: number };

export type InsightsTotals = {
  projects: number;
  projects_created: number;
  repos: number;
  cloud: ScanCounts;
  cicd: ScanCounts;
};

export type InsightsLastError = {
  scan_id: string;
  scan_type: ScanType;
  message: string | null;
  at: string | null;
};

export type NewCves = { count: number; latest: { id: string; severity: string }[] };

export type UserMetrics = {
  total: number;
  registered_in_window: number;
  registered_today: number;
  active_in_window: number;
  active_today: number;
  never_signed_in: number;
  pending_approval: number;
  disabled: number;
};

export type ProjectInsightsRow = {
  project_id: string;
  name: string;
  is_archived: boolean;
  created_at: string;
  repos: number;
  cloud: ScanCounts;
  cicd: ScanCounts;
  last_scan_at: string | null;
  last_error: InsightsLastError | null;
  cloud_scan_quota: CloudScanQuota;
  members: number;
  active_users: number;
  new_cves: NewCves;
};

export type ProjectInsights = {
  since: string;
  until: string;
  totals: InsightsTotals;
  users: UserMetrics;
  projects: ProjectInsightsRow[];
};

export type ScanRequestRow = {
  scan_id: string;
  project_id: string;
  /** Null once the project is deleted. */
  project_name: string | null;
  scan_type: ScanType;
  triggered_by: string | null;
  status: ScanStatus;
  stage: ScanStage | null;
  repo_url: string | null;
  branch: string | null;
  scan_label: string | null;
  ci_provider: string | null;
  ci_build_url: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  quota_exempt: boolean;
};

export type ScanRequestsPage = { total: number; items: ScanRequestRow[] };

export type InsightsRange = { since: string; until: string };

export type ScanRequestFilter = InsightsRange & {
  projectId?: string;
  scanType?: ScanType;
  status?: ScanStatus;
  limit?: number;
  offset?: number;
};

export function getProjectInsights({ since, until }: InsightsRange) {
  const p = new URLSearchParams({ since, until });
  return apiFetch<ProjectInsights>(`/admin/project-insights?${p}`);
}

export type ActiveUserRow = {
  user_id: string;
  email: string;
  name: string | null;
  days_active: number;
  last_seen_at: string | null;
};

export type TimelineEvent = {
  at: string;
  action: string;
  actor_type: string;
  actor_email: string | null;
  target_type: string | null;
  target_id: string | null;
  metadata: Record<string, unknown> | null;
};

export type ProjectActivity = {
  project_id: string;
  name: string;
  active_users: ActiveUserRow[];
  timeline: TimelineEvent[];
};

export function getProjectActivity(projectId: string, { since, until }: InsightsRange, limit = 100) {
  const p = new URLSearchParams({ since, until, limit: String(limit) });
  return apiFetch<ProjectActivity>(`/admin/project-insights/projects/${projectId}/activity?${p}`);
}

export function listScanRequests(f: ScanRequestFilter) {
  const p = new URLSearchParams({ since: f.since, until: f.until });
  if (f.projectId) p.set("project_id", f.projectId);
  if (f.scanType) p.set("scan_type", f.scanType);
  if (f.status) p.set("status", f.status);
  p.set("limit", String(f.limit ?? 25));
  p.set("offset", String(f.offset ?? 0));
  return apiFetch<ScanRequestsPage>(`/admin/project-insights/requests?${p}`);
}

/** `monthlyLimit: null` resets the project to the workspace default. */
export function setCloudScanLimit(projectId: string, monthlyLimit: number | null) {
  return apiFetch<CloudScanQuota>(`/admin/projects/${projectId}/cloud-scan-limit`, {
    method: "PUT",
    body: JSON.stringify({ monthly_limit: monthlyLimit }),
  });
}

/** Quota tone: muted under 80%, amber 80-99%, red at 100%. */
export function quotaTone(q: Pick<CloudScanQuota, "used" | "limit">): "ok" | "warn" | "full" {
  if (q.limit <= 0 || q.used >= q.limit) return "full";
  return q.used / q.limit >= 0.8 ? "warn" : "ok";
}

export function quotaFullMessage(q: Pick<CloudScanQuota, "used" | "limit">): string {
  if (q.limit === 0) return "Cloud scanning is paused for this project. Ask a portal admin to set a limit.";
  return `Cloud scan limit reached: ${q.used}/${q.limit} this month. Ask a portal admin to raise this project's limit.`;
}

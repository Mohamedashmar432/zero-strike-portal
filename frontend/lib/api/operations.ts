import { apiFetch } from "./client";

// See docs/OPERATIONS_AND_QUEUEING.md.
export type QueueKind = "cloud_scan" | "ai_analysis" | "remediation" | "compliance";

export type QueueJob = {
  kind: QueueKind;
  job_id: string;
  project_id: string;
  project_name: string | null;
  // The scan id (cloud scan, AI analysis, auto-fix) or audit id (compliance) the job belongs to.
  ref_id: string;
  status: "queued" | "running" | "failed";
  summary: string;
  stage: string | null;
  created_at: string;
  started_at: string | null;
  position: number | null;
  estimated_start_at: string | null;
  error_message: string | null;
  completed_at: string | null;
};

export type QueueSummary = {
  kind: QueueKind;
  label: string;
  capacity: number;
  running: number;
  queued: number;
  avg_duration_seconds: number;
  avg_is_default: boolean;
  oldest_queued_at: string | null;
};

export type SystemLoad = {
  source: "cgroup" | "host";
  cpu_percent: number;
  cpu_cores: number;
  memory_used_bytes: number;
  memory_limit_bytes: number;
  memory_percent: number | null;
  process_rss_bytes: number;
  subprocess_count: number;
  subprocess_rss_bytes: number;
  disk_used_bytes: number | null;
  disk_total_bytes: number | null;
};

export type QueueView = { server_time: string; queues: QueueSummary[]; jobs: QueueJob[] };
export type Operations = QueueView & { system: SystemLoad; recent_failures: QueueJob[] };

/** Every queued/running job the caller can see. One request feeds every queued tag on a page. */
export function getQueue() {
  return apiFetch<QueueView>("/queue");
}

export function getOperations() {
  return apiFetch<Operations>("/admin/operations");
}

/** "4:05", "1:02:03", or null once the moment has passed. */
export function formatCountdown(ms: number): string | null {
  if (ms <= 0) return null;
  const total = Math.ceil(ms / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.round(seconds / 60);
  return m < 60 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

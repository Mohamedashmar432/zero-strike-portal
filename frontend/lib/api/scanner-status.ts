import { apiFetch } from "./client";
import type { ScanStage } from "./scans";

export type BinaryChecklistItem = {
  os: string;
  arch: string;
  published: boolean;
  version: string | null;
  uploaded_at: string | null;
  uploaded_by: string | null;
  uploaded_by_email?: string | null;
};

export type RunningScanItem = {
  scan_id: string;
  project_id: string;
  started_at: string | null;
  stuck: boolean;
  stage: ScanStage | null;
  stage_started_at: string | null;
};

export type QueueStatus = {
  running: number;
  queued: number;
  max_concurrent: number;
  running_scans: RunningScanItem[];
};

export type FailureItem = {
  scan_id: string;
  project_id: string;
  scan_type: string;
  error_message: string | null;
  completed_at: string | null;
};

export type CloneWorkspaceStatus = {
  workdir_count: number;
  total_mb: number;
  free_mb: number;
  min_free_mb: number;
  max_repo_mb: number;
};

/** "512 MB" below a gigabyte, "1.5 GB" above. */
export function formatMegabytes(mb: number): string {
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
}

/** Caption for the clone-workspace cards: a leak or a full disk says so instead of just showing numbers. */
export function cloneWorkspaceWarning(clones: CloneWorkspaceStatus, runningScans: number): string | null {
  if (clones.min_free_mb > 0 && clones.free_mb < clones.min_free_mb) {
    return `Free disk is below the ${formatMegabytes(clones.min_free_mb)} floor - new clones are being refused.`;
  }
  if (clones.workdir_count > runningScans) {
    return "More clone directories than running work - leftovers are swept after the reap window.";
  }
  return null;
}

export type ScannerStatus = {
  engine_available: boolean;
  binaries: BinaryChecklistItem[];
  queue: QueueStatus;
  recent_failures: FailureItem[];
  clones: CloneWorkspaceStatus;
};

export function getScannerStatus() {
  return apiFetch<ScannerStatus>("/admin/scanner-status");
}

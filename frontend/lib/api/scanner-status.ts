import { apiFetch } from "./client";

export type BinaryChecklistItem = {
  os: string;
  arch: string;
  published: boolean;
  version: string | null;
  uploaded_at: string | null;
  uploaded_by: string | null;
};

export type RunningScanItem = {
  scan_id: string;
  project_id: string;
  started_at: string | null;
  stuck: boolean;
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

export type ScannerStatus = {
  engine_available: boolean;
  binaries: BinaryChecklistItem[];
  queue: QueueStatus;
  recent_failures: FailureItem[];
};

export function getScannerStatus() {
  return apiFetch<ScannerStatus>("/admin/scanner-status");
}

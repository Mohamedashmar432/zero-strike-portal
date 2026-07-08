import { apiFetch } from "./client";
import type { Page } from "./users";

export type AuditLogEntry = {
  id: string;
  actor_type: string;
  actor_user_id: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  project_id: string | null;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
};

export function listAuditLogs(page = 1, pageSize = 20) {
  return apiFetch<Page<AuditLogEntry>>(`/audit-logs?page=${page}&page_size=${pageSize}`);
}

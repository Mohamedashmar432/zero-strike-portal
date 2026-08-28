import { apiFetch } from "./client";
import type { Page } from "./users";

/** privilege = access changed · project = work inside a project · admin = portal-wide. */
export type AuditCategory = "privilege" | "project" | "admin";
/** "failed" is a cross-cutting filter, not a fourth category. */
export type AuditFilter = AuditCategory | "failed";

export type AuditLogEntry = {
  id: string;
  actor_type: string;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  category: AuditCategory;
  target_type: string | null;
  target_id: string | null;
  project_id: string | null;
  project_name: string | null;
  metadata: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
};

export type AuditLogCounts = {
  total: number;
  admin: number;
  project: number;
  privilege: number;
  failed: number;
};

/** Counts always describe the whole window, never the filtered slice. */
export type AuditLogPage = Page<AuditLogEntry> & {
  counts: AuditLogCounts;
  window_days: number;
};

export function listAuditLogs(
  opts: { days?: number; category?: AuditFilter; page?: number; pageSize?: number } = {}
) {
  const params = new URLSearchParams({
    days: String(opts.days ?? 1),
    page: String(opts.page ?? 1),
    page_size: String(opts.pageSize ?? 200),
  });
  if (opts.category) params.set("category", opts.category);
  return apiFetch<AuditLogPage>(`/audit-logs?${params}`);
}

/**
 * Actions are recorded as human titles ("Scan Created"), except for a handful of older
 * auth/admin ones written as slugs ("login", "admin.data.purge"). Normalising on read covers
 * both without a migration of rows that are meant to be immutable.
 */
export function formatAuditAction(action: string): string {
  if (/[A-Z]/.test(action)) return action;
  return action
    .split(/[._]/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

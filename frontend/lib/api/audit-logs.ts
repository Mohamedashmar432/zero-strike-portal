import { apiFetch } from "./client";
import { roleLabel } from "@/lib/role-labels";
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

/** A [since, until) range in ISO-8601, from the page's date pickers. */
export type DateRange = { since: string; until: string };

export function listAuditLogs(
  opts: DateRange & { category?: AuditFilter; page?: number; pageSize?: number }
) {
  const params = new URLSearchParams({
    since: opts.since,
    until: opts.until,
    page: String(opts.page ?? 1),
    page_size: String(opts.pageSize ?? 200),
  });
  if (opts.category) params.set("category", opts.category);
  return apiFetch<AuditLogPage>(`/audit-logs?${params}`);
}

export type SystemLogLevel = "warning" | "error" | "critical";

/** One backend log line at WARNING or above, persisted by the server's log sink. */
export type SystemLogEntry = {
  id: string;
  level: SystemLogLevel;
  logger: string;
  message: string;
  context: Record<string, unknown>;
  exception: string | null;
  created_at: string;
};

export function listSystemLogs(
  opts: DateRange & { level?: SystemLogLevel; page?: number; pageSize?: number }
) {
  const params = new URLSearchParams({
    since: opts.since,
    until: opts.until,
    level: opts.level ?? "warning",
    page: String(opts.page ?? 1),
    page_size: String(opts.pageSize ?? 200),
  });
  return apiFetch<Page<SystemLogEntry>>(`/audit-logs/system?${params}`);
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

/**
 * The one-line "what exactly changed" under an action: the affected account, plus the role
 * move for a role change. Reads metadata the backend already stores, so older rows without it
 * simply have no detail line.
 */
export function auditDetail(log: Pick<AuditLogEntry, "metadata">): string | null {
  const meta = log.metadata ?? {};
  const email = typeof meta.email === "string" ? meta.email : null;
  const from = typeof meta.from_role === "string" ? meta.from_role : null;
  const to = typeof meta.to_role === "string" ? meta.to_role : null;
  if (email && from && to) return `${email}: ${roleLabel(from)} → ${roleLabel(to)}`;
  return email;
}

import { ApiError, apiFetch, apiFetchBlob } from "./client";
import type { Severity } from "./findings";

// Mirrors backend/app/schemas/risk_acknowledgement.py (docs/RISK_ACCEPT_REVIEW_AND_VULN_REDESIGN.md).

export const MAX_EXTRA_RECIPIENTS = 10;
export const MAX_ACK_MESSAGE_CHARS = 2000;

export type Delivery = "pending" | "sent" | "failed" | "not_configured";
export type AckVia = "link" | "portal";
export type BatchState = "pending" | "acknowledged" | "superseded" | "expired";
export type AckState = "acknowledged" | "awaiting" | "none";

export type AckRecipient = {
  /** Masked unless the caller is a portal admin. */
  email: string;
  is_project_owner: boolean;
  delivery: Delivery;
  send_count: number;
  last_sent_at: string | null;
  token_expires_at: string | null;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  acknowledged_via: AckVia | null;
};

export type AckItem = {
  vulnerability_id: string;
  rule_id: string | null;
  rule_name: string | null;
  severity: Severity | null;
  kind: string | null;
  file_path: string;
  requested_by_email: string | null;
  requested_at: string;
  reviewed_by_email: string | null;
  reviewed_at: string | null;
  comment: string;
  auto_accepted: boolean;
  /** False once the finding was re-decided or revoked after this batch was sent. */
  current: boolean;
};

export type AckBatch = {
  id: string;
  project_id: string;
  created_at: string;
  created_by_email: string | null;
  message: string | null;
  item_count: number;
  state: BatchState;
  items_current: number;
  items_superseded: number;
  recipients_sent: number;
  recipients_acknowledged: number;
  recipients: AckRecipient[];
  /** Only on the single-batch read. */
  items: AckItem[] | null;
};

export type RiskAcceptanceRow = {
  vulnerability_id: string;
  fingerprint: string;
  rule_id: string | null;
  rule_name: string | null;
  severity: Severity | null;
  kind: string | null;
  file_path: string;
  review_status: "pending" | "accepted";
  comment: string;
  requested_by_email: string | null;
  requested_at: string;
  reviewed_by_email: string | null;
  reviewed_at: string | null;
  auto_accepted: boolean;
  ack_state: AckState;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  batch_id: string | null;
};

export type RiskAcceptanceList = {
  items: RiskAcceptanceRow[];
  total: number;
  page: number;
  page_size: number;
  accepted_count: number;
  pending_count: number;
  unacknowledged_count: number;
  latest_batch: AckBatch | null;
};

export type RiskAcceptanceStatusFilter = "all" | "accepted" | "pending";

export type PublicAckLookup = {
  project_name: string;
  created_at: string;
  message: string | null;
  expires_at: string | null;
  item_count: number;
  items: {
    rule_name: string | null;
    severity: Severity | null;
    kind: string | null;
    file_path: string;
    comment: string;
    accepted_at: string | null;
    auto_accepted: boolean;
  }[];
};

export type PublicAckResult = { acknowledged: boolean; project_name: string; item_count: number };

// --- pure helpers (tested) ----------------------------------------------------------------------

const EMAIL_RE = /^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]{2,}$/;

export function isValidEmail(value: string): boolean {
  return EMAIL_RE.test(value.trim());
}

/** Splits pasted text on commas, semicolons and whitespace; lowercases; drops empties. */
export function splitAddresses(raw: string): string[] {
  return raw
    .split(/[\s,;]+/)
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
}

/** Adds addresses to a chip list: dedupes, caps at MAX_EXTRA_RECIPIENTS, reports what was refused. */
export function addRecipients(
  current: string[],
  raw: string
): { next: string[]; invalid: string[]; overflow: number } {
  const next = [...current];
  const invalid: string[] = [];
  let overflow = 0;
  for (const addr of splitAddresses(raw)) {
    if (!isValidEmail(addr)) invalid.push(addr);
    else if (next.includes(addr)) continue;
    else if (next.length >= MAX_EXTRA_RECIPIENTS) overflow += 1;
    else next.push(addr);
  }
  return { next, invalid, overflow };
}

/** Total people the email goes to: the project owner plus any extras. */
export function recipientCount(extra: string[]): number {
  return 1 + extra.length;
}

/**
 * The UI may say "sent" only when at least one recipient's delivery is `sent`. Everything else is
 * reported as what it is, so a missing SMTP host never reads as a delivered request.
 */
export type DeliverySummary = {
  tone: "sent" | "partial" | "failed" | "not_configured" | "pending";
  label: string;
};

export function deliverySummary(recipients: Pick<AckRecipient, "delivery">[]): DeliverySummary {
  const sent = recipients.filter((r) => r.delivery === "sent").length;
  const n = recipients.length;
  if (sent > 0 && sent === n) return { tone: "sent", label: `SENT · ${sent}/${n}` };
  if (sent > 0) return { tone: "partial", label: `SENT TO ${sent} OF ${n}` };
  if (n > 0 && recipients.every((r) => r.delivery === "not_configured")) {
    return { tone: "not_configured", label: "NOT SENT · EMAIL NOT CONFIGURED" };
  }
  if (recipients.some((r) => r.delivery === "failed")) return { tone: "failed", label: "NOT SENT · DELIVERY FAILED" };
  return { tone: "pending", label: "NOT SENT · PENDING" };
}

export const BATCH_STATE_LABELS: Record<BatchState, string> = {
  pending: "Awaiting acknowledgement",
  acknowledged: "Acknowledged",
  superseded: "Superseded",
  expired: "Expired",
};

/** The token lives in the URL fragment (#token=<raw>), which a browser never sends to a server. */
export function tokenFromHash(hash: string): string | null {
  const m = /(?:^#|&)token=([^&]+)/.exec(hash);
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]).trim() || null;
  } catch {
    return null;
  }
}

// --- authenticated routes -----------------------------------------------------------------------

export function listRiskAcceptances(
  projectId: string,
  opts: { reviewStatus?: RiskAcceptanceStatusFilter; page?: number; pageSize?: number } = {}
) {
  const p = new URLSearchParams({
    review_status: opts.reviewStatus ?? "all",
    page: String(opts.page ?? 1),
    page_size: String(opts.pageSize ?? 25),
  });
  return apiFetch<RiskAcceptanceList>(`/projects/${projectId}/risk-acceptances?${p.toString()}`);
}

/** Admin-only previews of the live accepted risks. */
export function downloadRiskAcceptances(projectId: string, format: "pdf" | "csv") {
  return apiFetchBlob(`/projects/${projectId}/risk-acceptances/report.${format}`);
}

export function listAckBatches(projectId: string) {
  return apiFetch<{ items: AckBatch[] }>(`/projects/${projectId}/risk-acknowledgements`);
}

export function getAckBatch(projectId: string, batchId: string) {
  return apiFetch<AckBatch>(`/projects/${projectId}/risk-acknowledgements/${batchId}`);
}

export function createAckBatch(projectId: string, body: { extra_recipients: string[]; message?: string | null }) {
  return apiFetch<AckBatch>(`/projects/${projectId}/risk-acknowledgements`, {
    method: "POST",
    body: JSON.stringify({ extra_recipients: body.extra_recipients, message: body.message || null }),
  });
}

export function resendAckBatch(projectId: string, batchId: string) {
  return apiFetch<AckBatch>(`/projects/${projectId}/risk-acknowledgements/${batchId}/resend`, { method: "POST" });
}

export function acknowledgeAckBatch(projectId: string, batchId: string) {
  return apiFetch<AckBatch>(`/projects/${projectId}/risk-acknowledgements/${batchId}/acknowledge`, {
    method: "POST",
  });
}

export function downloadAckBatch(projectId: string, batchId: string, format: "pdf" | "csv") {
  return apiFetchBlob(`/projects/${projectId}/risk-acknowledgements/${batchId}/report.${format}`);
}

// --- public routes (no session) -----------------------------------------------------------------
// Plain fetch, not apiFetch: no bearer token is attached and a non-2xx can never reach the
// 401-refresh-and-redirect path. Identical 404 for a bad, used or expired token; 429 when limited.

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

async function publicPost<T>(path: string, token: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
    credentials: "omit",
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
  return res.json() as Promise<T>;
}

export const lookupAckToken = (token: string) => publicPost<PublicAckLookup>("/risk-acknowledgements/lookup", token);
export const acknowledgeByToken = (token: string) =>
  publicPost<PublicAckResult>("/risk-acknowledgements/acknowledge", token);

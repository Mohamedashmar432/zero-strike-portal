import { apiFetch } from "./client";

/**
 * Per-scan AI Auto-Fix allowance.
 *
 * Scoped to a scan, not a project: each scan is one repo at one commit, so the
 * budget refills naturally the next time that repo is scanned. `used` counts
 * distinct findings that already have a generated proposal, so regenerating or
 * revising a fix never charges twice.
 */
export type ScanAutoFixQuota = {
  scan_id: string;
  project_id: string;
  /** Global base allowance (Settings → Auto-Fix). */
  default_limit: number;
  /** Extra headroom an admin approved for this scan. */
  extra_granted: number;
  /** default_limit + extra_granted. */
  limit: number;
  used: number;
  remaining: number;
  /** Non-zero means a request is already awaiting review — don't offer another. */
  pending_request_count: number;
};

export type AutoFixQuotaRequestStatus = "pending" | "approved" | "rejected";

export type AutoFixQuotaRequest = {
  id: string;
  scan_id: string;
  project_id: string;
  project_name: string | null;
  requested_by: string;
  requested_by_email: string | null;
  requested_additional: number;
  reason: string;
  status: AutoFixQuotaRequestStatus;
  granted_additional: number | null;
  decision_note: string | null;
  decided_by: string | null;
  decided_by_email: string | null;
  decided_at: string | null;
  created_at: string;
};

export type AutoFixQuotaRequestList = {
  items: AutoFixQuotaRequest[];
  /** Full queue depth, not the filtered view — safe for a nav badge. */
  pending_count: number;
};

export function getScanAutoFixQuota(scanId: string) {
  return apiFetch<ScanAutoFixQuota>(`/scans/${scanId}/auto-fix/quota`);
}

export function listScanQuotaRequests(scanId: string) {
  return apiFetch<AutoFixQuotaRequestList>(`/scans/${scanId}/auto-fix/quota/requests`);
}

export function requestAutoFixQuota(
  scanId: string,
  body: { requested_additional: number; reason: string }
) {
  return apiFetch<AutoFixQuotaRequest>(`/scans/${scanId}/auto-fix/quota/requests`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// --- admin ------------------------------------------------------------------

export function listAllQuotaRequests(status?: AutoFixQuotaRequestStatus) {
  const qs = status ? `?status=${status}` : "";
  return apiFetch<AutoFixQuotaRequestList>(`/admin/auto-fix-quota/requests${qs}`);
}

export function decideQuotaRequest(
  requestId: string,
  body: { approve: boolean; granted_additional?: number; decision_note?: string }
) {
  return apiFetch<AutoFixQuotaRequest>(
    `/admin/auto-fix-quota/requests/${requestId}/decide`,
    { method: "POST", body: JSON.stringify(body) }
  );
}

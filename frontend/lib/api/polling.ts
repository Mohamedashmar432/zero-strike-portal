/**
 * Shared `refetchInterval` callbacks for "poll while a long-running job is still
 * pending/running" — the idiom already used for scan status, and the one an AI
 * analysis/auto-fix job will need too. Centralized so it isn't hand-rolled per page.
 */
const ACTIVE_STATUSES = new Set(["pending", "running", "in_progress"]);

function isActive(status: string | null | undefined): boolean {
  return !!status && ACTIVE_STATUSES.has(status);
}

/** For a query whose data is a single status-bearing object (e.g. a Scan). */
export function refetchWhileStatusActive<TData extends { status?: string | null }>(
  intervalMs = 3000
) {
  return (query: { state: { data?: TData } }) => (isActive(query.state.data?.status) ? intervalMs : false);
}

/** For a query whose data is a page of status-bearing items (e.g. a Scan list page). */
export function refetchWhileAnyItemActive<TItem extends { status?: string | null }>(
  intervalMs = 3000
) {
  return (query: { state: { data?: { items: TItem[] } } }) =>
    (query.state.data?.items ?? []).some((item) => isActive(item.status)) ? intervalMs : false;
}

// A scan is "active" for polling if either the scan itself is running OR its AI analysis is —
// a completed scan can still be mid-AI-analysis, and the list must keep refreshing to clear the tag.
type ScanLike = { status?: string | null; ai_analysis_status?: string | null };
function scanOrAiActive(s: ScanLike | undefined | null): boolean {
  return !!s && (isActive(s.status) || isActive(s.ai_analysis_status));
}

/** Single scan (detail page): poll while the scan OR its AI analysis is active. */
export function refetchWhileScanOrAiActive<TData extends ScanLike>(intervalMs = 3000) {
  return (query: { state: { data?: TData } }) => (scanOrAiActive(query.state.data) ? intervalMs : false);
}

/** Scan list page: poll while any scan OR its AI analysis is active. */
export function refetchWhileAnyScanOrAiActive<TItem extends ScanLike>(intervalMs = 3000) {
  return (query: { state: { data?: { items: TItem[] } } }) =>
    (query.state.data?.items ?? []).some(scanOrAiActive) ? intervalMs : false;
}

/** Dashboard stats: poll while any recent scan OR its AI analysis is active (`recent_scans` shape). */
export function refetchWhileAnyRecentScanActive<TItem extends ScanLike>(intervalMs = 3000) {
  return (query: { state: { data?: { recent_scans: TItem[] } } }) =>
    (query.state.data?.recent_scans ?? []).some(scanOrAiActive) ? intervalMs : false;
}

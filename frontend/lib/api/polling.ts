/**
 * Shared `refetchInterval` callbacks for "poll while a long-running job is still
 * pending/running" — the idiom already used for scan status, and the one an AI
 * analysis/auto-fix job will need too. Centralized so it isn't hand-rolled per page.
 */
// "queued" included so an AI job that's waiting in the queue (not yet picked up by a worker)
// still polls — otherwise the UI freezes on "queued" until something else triggers a refetch.
const ACTIVE_STATUSES = new Set(["pending", "queued", "running", "in_progress"]);

function isActive(status: string | null | undefined): boolean {
  return !!status && ACTIVE_STATUSES.has(status);
}

// Scan/AI jobs run minutes, not seconds. Poll at the base interval while a job is young, then
// back off once it's clearly long-running so we stop hammering the API. dataUpdateCount is the
// number of successful fetches so far — a good-enough proxy for "how long have we been polling".
const BACKOFF_AFTER_FETCHES = 12; // ~1 min at a 5s base
function backoff(baseMs: number, query: { state: { dataUpdateCount?: number } }): number {
  return (query.state.dataUpdateCount ?? 0) < BACKOFF_AFTER_FETCHES ? baseMs : baseMs * 2;
}

/** For a query whose data is a single status-bearing object (e.g. a Scan). */
export function refetchWhileStatusActive<TData extends { status?: string | null }>(
  intervalMs = 5000
) {
  return (query: { state: { data?: TData; dataUpdateCount?: number } }) =>
    isActive(query.state.data?.status) ? backoff(intervalMs, query) : false;
}

/** For a query whose data is a page of status-bearing items (e.g. a Scan list page). */
export function refetchWhileAnyItemActive<TItem extends { status?: string | null }>(
  intervalMs = 5000
) {
  return (query: { state: { data?: { items: TItem[] }; dataUpdateCount?: number } }) =>
    (query.state.data?.items ?? []).some((item) => isActive(item.status)) ? backoff(intervalMs, query) : false;
}

// A scan is "active" for polling if either the scan itself is running OR its AI analysis is —
// a completed scan can still be mid-AI-analysis, and the list must keep refreshing to clear the tag.
type ScanLike = { status?: string | null; ai_analysis_status?: string | null };
function scanOrAiActive(s: ScanLike | undefined | null): boolean {
  return !!s && (isActive(s.status) || isActive(s.ai_analysis_status));
}

/** Single scan (detail page): poll while the scan OR its AI analysis is active. */
export function refetchWhileScanOrAiActive<TData extends ScanLike>(intervalMs = 5000) {
  return (query: { state: { data?: TData; dataUpdateCount?: number } }) =>
    scanOrAiActive(query.state.data) ? backoff(intervalMs, query) : false;
}

/** Scan list page: poll while any scan OR its AI analysis is active. */
export function refetchWhileAnyScanOrAiActive<TItem extends ScanLike>(intervalMs = 5000) {
  return (query: { state: { data?: { items: TItem[] }; dataUpdateCount?: number } }) =>
    (query.state.data?.items ?? []).some(scanOrAiActive) ? backoff(intervalMs, query) : false;
}

/** Dashboard stats: poll while any recent scan OR its AI analysis is active (`recent_scans` shape). */
export function refetchWhileAnyRecentScanActive<TItem extends ScanLike>(intervalMs = 5000) {
  return (query: { state: { data?: { recent_scans: TItem[] }; dataUpdateCount?: number } }) =>
    (query.state.data?.recent_scans ?? []).some(scanOrAiActive) ? backoff(intervalMs, query) : false;
}

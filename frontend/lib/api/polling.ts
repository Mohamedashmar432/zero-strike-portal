/**
 * Shared `refetchInterval` callbacks for "poll while a long-running job is still
 * pending/running" — the idiom already used for scan status, and the one an AI
 * analysis/auto-fix job will need too. Centralized so it isn't hand-rolled per page.
 */
const ACTIVE_STATUSES = new Set(["pending", "running"]);

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

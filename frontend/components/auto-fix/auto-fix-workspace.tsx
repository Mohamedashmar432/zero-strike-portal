"use client";

/**
 * Master-detail review workspace: the proposal list on the left, the selected proposal on the right.
 *
 * Selection is URL-driven (?finding=…) rather than local state, so deep links from the scan page's
 * "Generate Fix" jump, from the comments drawer, and from a shared link all land on the same finding
 * — and the browser back button works. Below `lg` the grid collapses to one column and the list sits
 * above the detail.
 */

import { useQuery } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";
import { EmptyState } from "@/components/common/empty-state";
import type { AiFixProposal } from "@/lib/api/auto-fix";
import { listFindings } from "@/lib/api/findings";
import { queryKeys } from "@/lib/api/query-keys";
import { FixProposalDetail } from "./fix-proposal-detail";
import { compareProposals, FixProposalList } from "./fix-proposal-list";

// One findings request per scan, shared by every proposal's Evidence tab (TanStack caches it).
// Matches the propose cap (remediation_max_findings_per_job) with room to spare.
const FINDINGS_PAGE_SIZE = 200;

export function AutoFixWorkspace({
  scanId,
  proposals,
  canApprove,
  invalidateKey,
  commentCounts,
  onOpenComments,
  focusFindingId,
  threshold,
}: {
  scanId: string;
  proposals: AiFixProposal[];
  canApprove: boolean;
  invalidateKey: readonly unknown[];
  commentCounts: Map<string, number>;
  onOpenComments: (findingId: string | null) => void;
  focusFindingId?: string | null;
  /** AutoFixSummary.confidence_threshold — the server's effective bar. */
  threshold?: number;
}) {
  const router = useRouter();
  const params = useSearchParams();

  // Derived, not stored: the URL is the single source of truth for selection, falling back to the
  // deep-link target and then the first (highest-severity) proposal.
  const fromUrl = params.get("finding");
  const known = new Set(proposals.map((p) => p.finding_id));
  // The default must be the first proposal in DISPLAY order (compareProposals — the same comparator
  // the list sorts with), not proposals[0] from the API. The API order put the lowest-severity
  // finding first, so the reviewer opened the page on a MEDIUM while criticals sat above it.
  const firstDisplayed = useMemo(
    () => [...proposals].sort(compareProposals)[0]?.finding_id ?? null,
    [proposals]
  );
  const selectedId =
    (fromUrl && known.has(fromUrl) && fromUrl) ||
    (focusFindingId && known.has(focusFindingId) && focusFindingId) ||
    firstDisplayed;

  const select = useCallback(
    (findingId: string) => {
      const next = new URLSearchParams(params.toString());
      next.set("finding", findingId);
      // scroll:false — the detail pane swaps in place; yanking the viewport to the top would
      // undo the reviewer's position in the list.
      router.replace(`?${next.toString()}`, { scroll: false });
    },
    [params, router]
  );

  const { data: findingsPage, isLoading: findingsLoading } = useQuery({
    queryKey: queryKeys.scans.findings(scanId, { page: 1, pageSize: FINDINGS_PAGE_SIZE }),
    queryFn: () => listFindings(scanId, { page: 1, pageSize: FINDINGS_PAGE_SIZE }),
    staleTime: 5 * 60 * 1000, // findings are immutable for a completed scan
  });
  const findingsById = new Map((findingsPage?.items ?? []).map((f) => [f.id, f]));

  const selected = proposals.find((p) => p.finding_id === selectedId) ?? null;

  if (!proposals.length) {
    return (
      <EmptyState
        icon={Wand2}
        title="No fixes to review"
        description="No auto-fixable findings were produced for this scan."
      />
    );
  }

  return (
    <div className="grid min-h-0 items-start gap-4 lg:grid-cols-[minmax(17rem,22rem)_minmax(0,1fr)]">
      <FixProposalList
        proposals={proposals}
        selectedId={selectedId}
        onSelect={select}
        commentCounts={commentCounts}
        threshold={threshold}
      />
      {selected ? (
        <FixProposalDetail
          // Remount on selection change so tab state and the diff mode reset per proposal, rather
          // than a reviewer landing on the previous finding's "Checks" tab.
          key={selected.id}
          proposal={selected}
          finding={findingsById.get(selected.finding_id)}
          findingsLoading={findingsLoading}
          canApprove={canApprove}
          invalidateKey={invalidateKey}
          commentCount={commentCounts.get(selected.finding_id) ?? 0}
          onOpenComments={onOpenComments}
          scanId={scanId}
          threshold={threshold}
        />
      ) : (
        <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
          Select a finding to review its proposed fix.
        </div>
      )}
    </div>
  );
}

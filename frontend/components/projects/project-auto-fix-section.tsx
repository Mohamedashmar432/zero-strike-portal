"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, MessageSquare, Wand2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ActivityTimeline } from "@/components/auto-fix/activity-timeline";
import { AutoFixQuotaMeter } from "@/components/auto-fix/auto-fix-quota-meter";
import { AutoFixWorkspace } from "@/components/auto-fix/auto-fix-workspace";
import { CommentsDrawer } from "@/components/auto-fix/comments-drawer";
import { EmptyState } from "@/components/common/empty-state";
import { StatCard } from "@/components/common/stat-card";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  type AutoFixRiskRating,
  downloadScanBrief,
  getScanAutoFix,
  getScanCommentSummary,
  saveBlob,
  triggerScanAutoFix,
} from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import { refetchWhileAutoFixActive } from "@/lib/api/polling";
import { queryKeys } from "@/lib/api/query-keys";

const RISK_TONE: Record<AutoFixRiskRating, string> = {
  critical: "bg-severity-critical/15 text-severity-critical border-severity-critical/30",
  high: "bg-severity-high/15 text-severity-high border-severity-high/30",
  medium: "bg-severity-medium/15 text-severity-medium border-severity-medium/30",
  low: "bg-severity-low/15 text-severity-low border-severity-low/30",
  none: "",
};

function RiskBadge({ rating }: { rating: AutoFixRiskRating }) {
  if (rating === "none") return null;
  return (
    <Badge variant="outline" className={RISK_TONE[rating]}>
      {rating} risk
    </Badge>
  );
}

export function ProjectAutoFixSection({
  scanId,
  canApprove,
  focusFindingId,
}: {
  scanId: string;
  canApprove: boolean;
  focusFindingId?: string | null;
}) {
  const qc = useQueryClient();
  const router = useRouter();
  const params = useSearchParams();
  const key = queryKeys.ai.autofix.scan(scanId);

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => getScanAutoFix(scanId),
    refetchInterval: refetchWhileAutoFixActive(),
  });

  const trigger = useMutation({
    mutationFn: () => triggerScanAutoFix(scanId),
    onSuccess: (job) => {
      qc.setQueryData(key, job);
      // A run draws down the scan's allowance, so the readout in the control row
      // must not go stale.
      qc.invalidateQueries({ queryKey: queryKeys.ai.autofix.quota(scanId) });
      // A trim is announced at the moment of the click, not left to be inferred from a
      // shorter-than-expected result list.
      if (job.quota_skipped > 0) {
        toast.warning(
          `${job.quota_skipped} finding(s) were not queued — this scan's Auto-Fix allowance is ` +
            "full. Request more headroom from the allowance chip to include them."
        );
      }
    },
    // Surfaces the 409 from an exhausted allowance verbatim, which already tells the
    // user to request more headroom.
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed to start Auto-Fix"),
  });

  const brief = useMutation({
    mutationFn: async () => {
      const blob = await downloadScanBrief(scanId);
      saveBlob(blob, `zerostrike-remediation-${scanId}.md`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Could not generate the brief"),
  });

  const { data: commentSummary } = useQuery({
    queryKey: queryKeys.ai.autofix.commentSummary(scanId),
    queryFn: () => getScanCommentSummary(scanId),
  });
  const commentCounts = new Map((commentSummary?.by_finding ?? []).map((c) => [c.finding_id, c.count]));

  const proposals = data?.insight?.proposals ?? [];
  const summary = data?.insight?.summary;
  const status = data?.status;
  const active = status === "queued" || status === "in_progress";

  const [drawer, setDrawer] = useState<{ open: boolean; findingId: string | null }>({
    open: false,
    findingId: null,
  });
  const openComments = (findingId: string | null) => setDrawer({ open: true, findingId });

  // The workspace reads its selection from ?finding=, so "jump to this finding" from the comments
  // drawer means updating the query param through the router — a raw history.replaceState would not
  // notify useSearchParams, and the detail pane would silently not move.
  const selectFinding = (findingId: string) => {
    const next = new URLSearchParams(params.toString());
    next.set("finding", findingId);
    router.replace(`?${next.toString()}`, { scroll: false });
    setDrawer({ open: true, findingId });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Auto-Fix</h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            AI-generated fix proposals with confidence scoring — you review every diff before anything is
            applied. Nothing auto-commits.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* Per-scan allowance: a glanceable number in the control row rather
              than a band across the page. Detail + the request form live behind
              the click. */}
          <AutoFixQuotaMeter scanId={scanId} />
          {summary && <RiskBadge rating={summary.risk_rating} />}
          <Button
            variant="outline"
            size="icon"
            onClick={() => openComments(null)}
            title="View all comments"
            className="relative"
          >
            <MessageSquare />
            {commentSummary && commentSummary.total > 0 && (
              <span className="absolute -top-1.5 -right-1.5 flex min-w-4 items-center justify-center rounded-full bg-signal px-1 text-[10px] font-medium text-signal-foreground">
                {commentSummary.total}
              </span>
            )}
          </Button>
          {proposals.length > 0 && (
            <Button
              variant="outline"
              size="icon"
              onClick={() => brief.mutate()}
              disabled={brief.isPending}
              title="Download remediation brief (Markdown)"
            >
              <Download />
            </Button>
          )}
          <AiStatusBadge
            kind="autofix"
            status={status}
            startedAt={data?.started_at}
            progressCompleted={data?.progress_completed}
            progressTotal={data?.progress_total}
          />
          {/* "Fix remaining", not "Regenerate": a finding that already has a proposal is skipped
              rather than redrafted, because a redraft costs a full agent run and no quota. Use
              Regenerate on an individual proposal to redraft that one. */}
          <Button onClick={() => trigger.mutate()} disabled={active || trigger.isPending}>
            <Wand2 /> {proposals.length ? "Fix remaining findings" : "Generate fixes"}
          </Button>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <StatCard size="sm" label="Findings" value={summary.total_findings} />
          <StatCard size="sm" label="AI can fix" value={summary.ai_fixable} />
          <StatCard size="sm" label="Needs review on fix" value={summary.needs_review_on_fix} />
          <StatCard size="sm" label="Can't fix — manual" value={summary.cannot_fix} />
          <StatCard size="sm" label="PRs opened" value={summary.pr_created} />
        </div>
      )}

      <ActivityTimeline scanId={scanId} />

      {status === "failed" && (
        <Alert variant="destructive">
          <AlertTitle>Fix generation failed</AlertTitle>
          <AlertDescription>{data?.error_message ?? "Please try again."}</AlertDescription>
        </Alert>
      )}
      {active && (
        <Alert>
          <AlertTitle>Generating fixes…</AlertTitle>
          <AlertDescription>This runs in the background — the page updates automatically.</AlertDescription>
        </Alert>
      )}
      {/* Why the last run covered fewer findings than were submitted. Without this the missing
          proposals read as "the AI couldn't fix them" rather than "it never looked at them". */}
      {status === "completed" && (data?.quota_skipped || data?.skipped_existing) ? (
        <Alert>
          <AlertTitle>This run did not cover every finding submitted</AlertTitle>
          <AlertDescription className="space-y-1">
            {data.quota_skipped > 0 && (
              <p>
                <strong>{data.quota_skipped} finding(s) were blocked by the allowance.</strong> This
                scan&apos;s Auto-Fix budget is full — request more headroom from the allowance chip
                above, then run again to include them.
              </p>
            )}
            {data.skipped_existing > 0 && (
              <p>
                {data.skipped_existing} finding(s) already had a proposal and were left as they are —
                no AI call was spent on them. Use <em>Regenerate</em> on an individual proposal to
                redraft it.
              </p>
            )}
          </AlertDescription>
        </Alert>
      ) : null}

      {isLoading || (active && !proposals.length) ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(17rem,22rem)_minmax(0,1fr)]">
          <div className="space-y-2">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
          <Skeleton className="h-64 w-full" />
        </div>
      ) : proposals.length ? (
        <AutoFixWorkspace
          scanId={scanId}
          proposals={proposals}
          canApprove={canApprove}
          invalidateKey={key}
          commentCounts={commentCounts}
          onOpenComments={openComments}
          focusFindingId={focusFindingId}
          threshold={summary?.confidence_threshold}
        />
      ) : status === "completed" ? (
        <EmptyState
          icon={Wand2}
          title="No fixes to review"
          description="No auto-fixable findings were produced for this scan."
        />
      ) : (
        <EmptyState
          icon={Wand2}
          title="Generate fixes"
          description="Run Auto-Fix to produce reviewable patch proposals for this scan's findings."
        />
      )}

      <CommentsDrawer
        open={drawer.open}
        onOpenChange={(v) => setDrawer((d) => ({ ...d, open: v }))}
        scanId={scanId}
        proposals={proposals}
        commentCounts={commentCounts}
        selectedId={drawer.findingId}
        onJump={selectFinding}
      />
    </div>
  );
}

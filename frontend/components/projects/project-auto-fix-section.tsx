"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import { useEffect } from "react";
import { toast } from "sonner";
import { FixProposalCard } from "@/components/auto-fix/fix-proposal-card";
import { EmptyState } from "@/components/common/empty-state";
import { StatCard } from "@/components/common/stat-card";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { getScanAutoFix, triggerScanAutoFix } from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import { refetchWhileStatusActive } from "@/lib/api/polling";
import { queryKeys } from "@/lib/api/query-keys";

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
  const key = queryKeys.ai.autofix.scan(scanId);

  const { data, isLoading } = useQuery({
    queryKey: key,
    queryFn: () => getScanAutoFix(scanId),
    refetchInterval: refetchWhileStatusActive(),
  });

  const trigger = useMutation({
    mutationFn: () => triggerScanAutoFix(scanId),
    onSuccess: (job) => qc.setQueryData(key, job),
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed to start Auto-Fix"),
  });

  const proposals = data?.insight?.proposals ?? [];
  const summary = data?.insight?.summary;
  const status = data?.status;
  const active = status === "queued" || status === "in_progress";

  useEffect(() => {
    if (focusFindingId && proposals.length) {
      document.getElementById(`fix-${focusFindingId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [focusFindingId, proposals.length]);

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
        <div className="flex items-center gap-2">
          <AiStatusBadge
            kind="autofix"
            status={status}
            startedAt={data?.started_at}
            progressCompleted={data?.progress_completed}
            progressTotal={data?.progress_total}
          />
          <Button onClick={() => trigger.mutate()} disabled={active || trigger.isPending}>
            <Wand2 /> {proposals.length ? "Regenerate fixes" : "Generate fixes"}
          </Button>
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard size="sm" label="Findings" value={summary.total_findings} />
          <StatCard size="sm" label="Auto-fixable" value={summary.auto_fixable} />
          <StatCard size="sm" label="Manual review" value={summary.manual_review} />
          <StatCard size="sm" label="PRs opened" value={summary.pr_created} />
        </div>
      )}

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

      {isLoading || (active && !proposals.length) ? (
        <div className="space-y-3">
          <Skeleton className="h-40 w-full" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : proposals.length ? (
        <div className="space-y-4">
          {proposals.map((p) => (
            <FixProposalCard key={p.id} proposal={p} canApprove={canApprove} invalidateKey={key} />
          ))}
        </div>
      ) : status === "completed" ? (
        <EmptyState icon={Wand2} title="No fixes to review" description="No auto-fixable findings were produced for this scan." />
      ) : (
        <EmptyState
          icon={Wand2}
          title="Generate fixes"
          description="Run Auto-Fix to produce reviewable patch proposals for this scan's findings."
        />
      )}
    </div>
  );
}

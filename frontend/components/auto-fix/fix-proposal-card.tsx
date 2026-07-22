"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, ExternalLink, GitPullRequest, X } from "lucide-react";
import { toast } from "sonner";
import { DiffView } from "@/components/auto-fix/diff-view";
import { FixReviewStateBadge } from "@/components/auto-fix/fix-review-state-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  approveFixProposal,
  type AiFixProposal,
  dismissFixProposal,
  downloadFixPatch,
} from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

function confidenceTone(score: number): string {
  if (score >= 80) return "text-emerald-500";
  if (score >= 50) return "text-severity-medium";
  return "text-muted-foreground";
}

export function FixProposalCard({
  proposal,
  canApprove,
  invalidateKey,
}: {
  proposal: AiFixProposal;
  canApprove: boolean;
  invalidateKey: readonly unknown[];
}) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: invalidateKey });

  const onError = (err: unknown) =>
    toast.error(err instanceof ApiError ? err.message : "Something went wrong");

  const approve = useMutation({
    mutationFn: () => approveFixProposal(proposal.id),
    onSuccess: () => {
      toast.success("Approved — creating the pull request…");
      invalidate();
    },
    onError,
  });

  const dismiss = useMutation({
    mutationFn: () => dismissFixProposal(proposal.id),
    onSuccess: () => {
      toast.success("Proposal dismissed");
      invalidate();
    },
    onError,
  });

  const download = useMutation({
    mutationFn: () => downloadFixPatch(proposal.id),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `zerostrike-fix-${proposal.id}.patch`;
      a.click();
      URL.revokeObjectURL(url);
    },
    onError,
  });

  const rs = proposal.review_state;
  const inFlight = rs === "approved" || rs === "applying" || approve.isPending;
  const canApproveNow = canApprove && proposal.can_fix && (rs === "proposed" || rs === "validated" || rs === "failed");
  const canDismiss = rs !== "dismissed" && rs !== "pr_open";
  const hasPatch = !!(proposal.original_code && proposal.patched_code);

  return (
    <Card id={`fix-${proposal.finding_id}`} className={cn(rs === "dismissed" && "opacity-60")}>
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          {proposal.finding_severity && <SeverityBadge severity={proposal.finding_severity} />}
          <span className="font-medium">{proposal.finding_rule_name ?? "Finding"}</span>
          <FixReviewStateBadge state={rs} />
          {proposal.can_fix && (
            <span className={cn("ml-auto font-mono text-xs", confidenceTone(proposal.confidence_score))}>
              {Math.round(proposal.confidence_score)}% confidence
            </span>
          )}
        </div>
        {proposal.finding_file && (
          <p className="font-mono text-xs text-muted-foreground">
            {proposal.finding_file}
            {proposal.finding_start_line ? `:${proposal.finding_start_line}` : ""}
          </p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {proposal.explanation && <p className="text-sm text-muted-foreground">{proposal.explanation}</p>}

        {hasPatch ? (
          <DiffView original={proposal.original_code!} patched={proposal.patched_code!} />
        ) : (
          <p className="rounded-md border border-severity-medium/30 bg-severity-medium/5 px-3 py-2 text-sm">
            {proposal.manual_review_reason ?? "This finding needs manual review — no safe automatic patch was produced."}
          </p>
        )}

        {proposal.validation && (
          <p className="text-xs text-muted-foreground">
            Re-scan: {proposal.validation.target_cleared ? "finding cleared" : "finding not cleared"}
            {typeof proposal.validation.new_finding_count === "number" &&
              ` · ${proposal.validation.new_finding_count} new finding(s)`}
          </p>
        )}
        {proposal.risk_notes && <p className="text-xs text-severity-medium">Risk: {proposal.risk_notes}</p>}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          {proposal.pr_url && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => window.open(proposal.pr_url!, "_blank", "noopener,noreferrer")}
            >
              <GitPullRequest /> View PR <ExternalLink />
            </Button>
          )}
          {canApproveNow && (
            <Button size="sm" onClick={() => approve.mutate()} disabled={inFlight}>
              <GitPullRequest /> {inFlight ? "Creating PR…" : "Approve & Create PR"}
            </Button>
          )}
          {hasPatch && (
            <Button size="sm" variant="outline" onClick={() => download.mutate()} disabled={download.isPending}>
              <Download /> Download .patch
            </Button>
          )}
          {canDismiss && (
            <Button size="sm" variant="ghost" onClick={() => dismiss.mutate()} disabled={dismiss.isPending}>
              <X /> Dismiss
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

"use client";

import { ChevronRight, MessageSquare } from "lucide-react";
import { useState } from "react";
import { DiffView } from "@/components/auto-fix/diff-view";
import { FixChat } from "@/components/auto-fix/fix-chat";
import { FixReviewStateBadge } from "@/components/auto-fix/fix-review-state-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { AiFixProposal } from "@/lib/api/auto-fix";
import { cn } from "@/lib/utils";
import {
  confidenceTone,
  CreatePrButton,
  DependencyUpdatePicker,
  FALLBACK_THRESHOLD,
  fixCapabilities,
  FixSecondaryActions,
} from "./fix-actions";

export function FixProposalCard({
  proposal,
  canApprove,
  invalidateKey,
  commentCount = 0,
  expanded,
  onToggle,
  onOpenComments,
}: {
  proposal: AiFixProposal;
  canApprove: boolean;
  invalidateKey: readonly unknown[];
  commentCount?: number;
  expanded: boolean;
  onToggle: () => void;
  onOpenComments: (findingId: string) => void;
}) {
  const [askOpen, setAskOpen] = useState(false);
  // This card renders on the scan page, which has no AutoFixSummary in scope; the confidence figure
  // here is informational (the approval dialog it opens states the bar it actually used).
  const threshold = FALLBACK_THRESHOLD;
  const rs = proposal.review_state;
  // Capability derivation and the write mutations live in fix-actions, shared with the workspace's
  // detail pane — one implementation of "can this be approved, and what happens when it is".
  const { hasPatch, manualReason, canRevise } = fixCapabilities(proposal, canApprove);

  return (
    <Card id={`fix-${proposal.finding_id}`} className={cn("gap-0 py-0", rs === "dismissed" && "opacity-60")}>
      <CardHeader className="gap-2 p-4">
        <div className="flex items-center gap-2">
          <button type="button" onClick={onToggle} className="flex min-w-0 flex-1 items-center gap-2 text-left">
            <ChevronRight className={cn("size-4 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-90")} />
            {proposal.finding_severity && <SeverityBadge severity={proposal.finding_severity} />}
            <span className="truncate font-medium">{proposal.finding_rule_name ?? "Finding"}</span>
            <FixReviewStateBadge state={rs} />
          </button>

          {proposal.can_fix && (
            <span
              className={cn(
                "hidden shrink-0 font-mono text-xs sm:inline",
                confidenceTone(proposal.confidence_score, threshold)
              )}
            >
              {Math.round(proposal.confidence_score)}%
            </span>
          )}
          {commentCount > 0 && (
            <button
              type="button"
              onClick={() => onOpenComments(proposal.finding_id)}
              className="flex shrink-0 items-center gap-1 rounded-full bg-brand/10 px-2 py-0.5 text-xs text-brand"
              title="View comments"
            >
              <MessageSquare className="size-3" /> {commentCount}
            </button>
          )}

          {/* Primary action lives at the top: after reviewing, the reviewer creates the PR here. */}
          <CreatePrButton proposal={proposal} canApprove={canApprove} invalidateKey={invalidateKey} />
        </div>

        {proposal.finding_file && (
          <p className="pl-6 font-mono text-xs text-muted-foreground">
            {proposal.finding_file}
            {proposal.finding_start_line ? `:${proposal.finding_start_line}` : ""}
          </p>
        )}
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-3 border-t p-4">
          {proposal.explanation && proposal.explanation !== proposal.manual_review_reason && (
            <p className="text-sm text-muted-foreground">{proposal.explanation}</p>
          )}

          {/* Manual-review reason — shown even when a patch exists, so the reviewer knows why it
              can't be auto-applied (e.g. no connected repo). */}
          {manualReason && (
            <p className="rounded-md border border-severity-medium/30 bg-severity-medium/5 px-3 py-2 text-sm">
              <span className="font-medium">Needs manual review: </span>
              {manualReason}
            </p>
          )}

          {hasPatch ? (
            <DiffView
              original={proposal.original_code!}
              patched={proposal.patched_code!}
              filePath={proposal.file_path ?? proposal.finding_file}
            />
          ) : (
            !manualReason && (
              <p className="rounded-md border border-severity-medium/30 bg-severity-medium/5 px-3 py-2 text-sm">
                This finding needs manual review — no safe automatic patch was produced.
              </p>
            )
          )}

          {proposal.dependency_update && proposal.dependency_update.available_versions.length > 0 && canRevise && (
            <DependencyUpdatePicker proposalId={proposal.id} dep={proposal.dependency_update} invalidateKey={invalidateKey} />
          )}

          {proposal.validation && (
            <p className="text-xs text-muted-foreground">
              Re-scan: {proposal.validation.target_cleared ? "finding cleared" : "finding not cleared"}
              {typeof proposal.validation.new_finding_count === "number" &&
                ` · ${proposal.validation.new_finding_count} new finding(s)`}
            </p>
          )}
          {proposal.risk_notes && <p className="text-xs text-severity-medium">Risk: {proposal.risk_notes}</p>}

          {/* Footer actions: helpers on the left, destructive on the right. */}
          <div className="pt-1">
            <FixSecondaryActions
              proposal={proposal}
              invalidateKey={invalidateKey}
              commentCount={commentCount}
              askOpen={askOpen}
              onToggleAsk={() => setAskOpen((v) => !v)}
              onOpenComments={onOpenComments}
            />
          </div>

          {askOpen && rs !== "dismissed" && (
            <FixChat proposalId={proposal.id} canRevise={canRevise} invalidateKey={invalidateKey} />
          )}
        </CardContent>
      )}
    </Card>
  );
}

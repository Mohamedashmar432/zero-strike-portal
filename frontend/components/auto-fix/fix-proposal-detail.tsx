"use client";

/**
 * The detail pane: everything about ONE proposal, tabbed so the diff stays the default view and the
 * supporting material (scanner evidence, the pipeline verdicts, discussion) is one click away rather
 * than stacked below it.
 */

import { useMutation } from "@tanstack/react-query";
import { Columns2, Download, Rows2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ActivityTimeline } from "@/components/auto-fix/activity-timeline";
import { DiffView } from "@/components/auto-fix/diff-view";
import { FixChat } from "@/components/auto-fix/fix-chat";
import { FixReviewStateBadge } from "@/components/auto-fix/fix-review-state-badge";
import { FixStagePanel } from "@/components/auto-fix/fix-stage-panel";
import { EvidencePanel } from "@/components/auto-fix/evidence-panel";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  type AiFixProposal,
  downloadFixPatch,
  type FixReviewState,
  saveBlob,
} from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import type { Finding } from "@/lib/api/findings";
import { cn } from "@/lib/utils";
import {
  confidenceTone,
  CreatePrButton,
  DependencyUpdatePicker,
  FALLBACK_THRESHOLD,
  fixCapabilities,
  FixSecondaryActions,
} from "./fix-actions";

function DiffModeToggle({ mode, onChange }: { mode: "unified" | "split"; onChange: (m: "unified" | "split") => void }) {
  // Two buttons rather than a toggle-group primitive — it's a binary choice and this needs no new dep.
  return (
    <div className="inline-flex items-center rounded-md border p-[2px]" role="group" aria-label="Diff layout">
      {(["unified", "split"] as const).map((m) => {
        const Icon = m === "unified" ? Rows2 : Columns2;
        return (
          <button
            key={m}
            type="button"
            onClick={() => onChange(m)}
            aria-pressed={mode === m}
            title={`${m} view`}
            className={cn(
              "flex items-center gap-1 rounded px-2 py-0.5 text-xs capitalize transition-colors",
              mode === m ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon className="size-3.5" /> {m}
          </button>
        );
      })}
    </div>
  );
}

export function FixProposalDetail({
  proposal,
  finding,
  findingsLoading,
  canApprove,
  invalidateKey,
  commentCount = 0,
  onOpenComments,
  scanId,
  threshold = FALLBACK_THRESHOLD,
}: {
  proposal: AiFixProposal;
  finding: Finding | undefined;
  findingsLoading: boolean;
  canApprove: boolean;
  invalidateKey: readonly unknown[];
  commentCount?: number;
  onOpenComments: (findingId: string) => void;
  scanId: string;
  /** Effective bar from AutoFixSummary.confidence_threshold. */
  threshold?: number;
}) {
  const [mode, setMode] = useState<"unified" | "split">("unified");
  const [askOpen, setAskOpen] = useState(false);
  const caps = fixCapabilities(proposal, canApprove);

  const download = useMutation({
    mutationFn: async () => {
      const blob = await downloadFixPatch(proposal.id);
      saveBlob(blob, `zerostrike-fix-${proposal.id}.patch`);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "No patch available"),
  });

  return (
    <div className="flex min-w-0 flex-col rounded-lg border">
      <div className="space-y-2 border-b p-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              {proposal.finding_severity && <SeverityBadge severity={proposal.finding_severity} />}
              <h3 className="font-semibold">{proposal.finding_rule_name ?? "Finding"}</h3>
              <FixReviewStateBadge state={proposal.review_state as FixReviewState} />
              {proposal.can_fix && (
                <span className={cn("font-mono text-xs", confidenceTone(proposal.confidence_score, threshold))}>
                  {Math.round(proposal.confidence_score)}% confidence
                </span>
              )}
            </div>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {proposal.file_path ?? proposal.finding_file ?? "—"}
              {proposal.finding_start_line ? `:${proposal.finding_start_line}` : ""}
            </p>
          </div>
          <CreatePrButton
            proposal={proposal}
            canApprove={canApprove}
            invalidateKey={invalidateKey}
            threshold={threshold}
          />
        </div>

        {proposal.explanation && proposal.explanation !== proposal.manual_review_reason && (
          <p className="text-sm text-muted-foreground">{proposal.explanation}</p>
        )}

        {/* Shown even when a patch exists, so the reviewer knows why it can't be auto-applied. */}
        {caps.manualReason && (
          <p className="rounded-md border border-severity-medium/30 bg-severity-medium/5 px-3 py-2 text-sm">
            <span className="font-medium">Needs manual review: </span>
            {caps.manualReason}
          </p>
        )}
        {/* review_state="failed" is set when the whole apply job errored (clone, git, PR call) —
            without the reason the card just says "failed" and a batch outcome is unreadable. */}
        {caps.failedReason && (
          <p className="rounded-md border border-severity-high/30 bg-severity-high/5 px-3 py-2 text-sm">
            <span className="font-medium">Apply failed: </span>
            {caps.failedReason}
          </p>
        )}
        {proposal.risk_notes && <p className="text-xs text-severity-medium">Risk: {proposal.risk_notes}</p>}
      </div>

      <div className="min-w-0 p-4">
        <Tabs defaultValue="diff">
          <TabsList variant="line">
            <TabsTrigger value="diff">Patch</TabsTrigger>
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="pipeline">Checks</TabsTrigger>
            <TabsTrigger value="discussion">Discussion{commentCount ? ` (${commentCount})` : ""}</TabsTrigger>
            <TabsTrigger value="activity">Activity</TabsTrigger>
          </TabsList>

          <TabsContent value="diff" className="min-w-0 space-y-3">
            {caps.hasPatch ? (
              <>
                <div className="flex items-center justify-between gap-2">
                  <DiffModeToggle mode={mode} onChange={setMode} />
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => download.mutate()}
                    disabled={download.isPending}
                  >
                    <Download /> .patch
                  </Button>
                </div>
                {/* Wide diffs scroll inside their own container; the page never scrolls sideways. */}
                <div className="min-w-0 overflow-x-auto">
                  <DiffView
                    original={proposal.original_code!}
                    patched={proposal.patched_code!}
                    filePath={proposal.file_path ?? proposal.finding_file}
                    mode={mode}
                  />
                </div>
              </>
            ) : (
              <p className="rounded-md border border-severity-medium/30 bg-severity-medium/5 px-3 py-2 text-sm">
                No automatic patch was produced for this finding — see <span className="font-medium">Checks</span> for
                why, and <span className="font-medium">Evidence</span> for what the scanner found.
              </p>
            )}

            {proposal.dependency_update && proposal.dependency_update.available_versions.length > 0 && caps.canRevise && (
              <DependencyUpdatePicker
                proposalId={proposal.id}
                dep={proposal.dependency_update}
                invalidateKey={invalidateKey}
              />
            )}

            <FixSecondaryActions
              proposal={proposal}
              invalidateKey={invalidateKey}
              commentCount={commentCount}
              askOpen={askOpen}
              onToggleAsk={() => setAskOpen((v) => !v)}
              onOpenComments={onOpenComments}
            />
            {askOpen && proposal.review_state !== "dismissed" && (
              <FixChat proposalId={proposal.id} canRevise={caps.canRevise} invalidateKey={invalidateKey} />
            )}
          </TabsContent>

          <TabsContent value="evidence" className="min-w-0">
            <EvidencePanel proposal={proposal} finding={finding} isLoading={findingsLoading} />
          </TabsContent>

          <TabsContent value="pipeline" className="min-w-0">
            <FixStagePanel proposal={proposal} />
          </TabsContent>

          <TabsContent value="discussion" className="min-w-0 space-y-3">
            <p className="text-sm text-muted-foreground">
              Ask the AI about this fix, or request a change — a change request regenerates the patch.
            </p>
            <FixChat proposalId={proposal.id} canRevise={caps.canRevise} invalidateKey={invalidateKey} />
            <Button size="sm" variant="outline" onClick={() => onOpenComments(proposal.finding_id)}>
              Open team comments{commentCount ? ` (${commentCount})` : ""}
            </Button>
          </TabsContent>

          <TabsContent value="activity" className="min-w-0">
            <ActivityTimeline scanId={scanId} findingId={proposal.finding_id} defaultOpen />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

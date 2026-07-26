"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronRight,
  ExternalLink,
  GitPullRequest,
  MessageSquare,
  Package,
  Sparkles,
  Wand2,
  X,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { DiffView } from "@/components/auto-fix/diff-view";
import { FixChat } from "@/components/auto-fix/fix-chat";
import { FixReviewStateBadge } from "@/components/auto-fix/fix-review-state-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  approveFixProposal,
  type AiFixProposal,
  type DependencyUpdate,
  dismissFixProposal,
  reviseFixProposal,
} from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/** SCA version picker (image 1.png): AI recommends the safe version (preselected); choosing another
 * re-runs the fix agent to regenerate the manifest bump for that version. Scanner SCA data only. */
function DependencyUpdatePicker({
  proposalId,
  dep,
  invalidateKey,
}: {
  proposalId: string;
  dep: DependencyUpdate;
  invalidateKey: readonly unknown[];
}) {
  const qc = useQueryClient();
  const [version, setVersion] = useState(dep.recommended_version ?? dep.available_versions[0] ?? "");
  const revise = useMutation({
    mutationFn: (v: string) =>
      reviseFixProposal(proposalId, {
        instruction: `Update dependency ${dep.package ?? ""} to version ${v}${dep.manifest ? ` in ${dep.manifest}` : ""}.`,
      }),
    onSuccess: () => {
      toast.success("Regenerating the dependency update…");
      qc.invalidateQueries({ queryKey: invalidateKey });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed to update"),
  });

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border bg-muted/20 px-3 py-2 text-sm">
      <Package className="size-4 text-muted-foreground" />
      <span className="font-mono font-medium">{dep.package}</span>
      {dep.current_version && (
        <span className="text-muted-foreground">
          {dep.current_version} <span aria-hidden>→</span>
        </span>
      )}
      <Select value={version} onValueChange={(v) => setVersion(v ?? "")}>
        <SelectTrigger className="h-8 w-44">
          <SelectValue placeholder="Choose version" />
        </SelectTrigger>
        <SelectContent>
          {dep.available_versions.map((v) => (
            <SelectItem key={v} value={v}>
              {v}
              {v === dep.recommended_version ? " — recommended" : ""}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Button size="sm" onClick={() => version && revise.mutate(version)} disabled={revise.isPending || !version}>
        <Wand2 /> Apply version
      </Button>
    </div>
  );
}

function confidenceTone(score: number): string {
  if (score >= 80) return "text-emerald-500";
  if (score >= 50) return "text-severity-medium";
  return "text-muted-foreground";
}

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
  const qc = useQueryClient();
  const [askOpen, setAskOpen] = useState(false);
  const [confirmPr, setConfirmPr] = useState(false);
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

  const rs = proposal.review_state;
  const inFlight = rs === "approved" || rs === "applying" || approve.isPending;
  const CONFIDENCE_THRESHOLD = 80; // the auto-approve bar; below it a human is vouching for the fix
  const hasPatch = !!(proposal.original_code && proposal.patched_code);
  const canDismiss = rs !== "dismissed" && rs !== "pr_open";
  const canRevise = rs === "proposed" || rs === "manual_review" || rs === "validated" || rs === "failed";
  const manualReason =
    rs === "manual_review" && proposal.manual_review_reason ? proposal.manual_review_reason : null;
  // A human owner/admin can create the PR for any reviewable proposal that has a patch — confidence
  // only gates *auto*-approval, not a human who's read the diff. The apply job still re-scans and
  // refuses to push anything that introduces new findings. manual_review means the write already
  // failed (e.g. no connected repo), so the button is shown disabled with the reason.
  const lowConfidence = proposal.confidence_score < CONFIDENCE_THRESHOLD;
  const canCreatePr =
    canApprove && proposal.can_fix && hasPatch && (rs === "proposed" || rs === "validated" || rs === "failed");
  const prBlocked =
    canApprove && proposal.can_fix && hasPatch && rs === "manual_review" ? manualReason ?? "Needs manual review." : null;

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
            <span className={cn("hidden shrink-0 font-mono text-xs sm:inline", confidenceTone(proposal.confidence_score))}>
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
          {proposal.pr_url ? (
            <Button
              size="sm"
              variant="outline"
              className="shrink-0"
              onClick={() => window.open(proposal.pr_url!, "_blank", "noopener,noreferrer")}
            >
              <GitPullRequest /> View PR <ExternalLink />
            </Button>
          ) : inFlight ? (
            <Button size="sm" className="shrink-0" disabled>
              <GitPullRequest /> Applying…
            </Button>
          ) : canCreatePr ? (
            <Button size="sm" className="shrink-0" onClick={() => setConfirmPr(true)}>
              <GitPullRequest /> Create PR
            </Button>
          ) : prBlocked ? (
            <Button size="sm" variant="outline" className="shrink-0" disabled title={prBlocked}>
              <GitPullRequest /> Create PR
            </Button>
          ) : null}
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
          <div className="flex items-center gap-2 pt-1">
            {rs !== "dismissed" && (
              <Button
                size="sm"
                variant={askOpen ? "secondary" : "outline"}
                onClick={() => setAskOpen((v) => !v)}
              >
                <Sparkles /> Ask AI
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => onOpenComments(proposal.finding_id)}>
              <MessageSquare /> Comments{commentCount ? ` (${commentCount})` : ""}
            </Button>
            {canDismiss && (
              <Button size="sm" variant="ghost" className="ml-auto text-muted-foreground" onClick={() => dismiss.mutate()} disabled={dismiss.isPending}>
                <X /> Dismiss
              </Button>
            )}
          </div>

          {askOpen && rs !== "dismissed" && (
            <FixChat proposalId={proposal.id} canRevise={canRevise} invalidateKey={invalidateKey} />
          )}
        </CardContent>
      )}

      <Dialog open={confirmPr} onOpenChange={setConfirmPr}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create pull request?</DialogTitle>
            <DialogDescription>
              ZeroStrike will push a branch and open a pull request titled{" "}
              <span className="font-mono text-foreground">
                zero-strike/security fix: {proposal.finding_rule_name ?? "finding"}
              </span>{" "}
              on the connected repository. Nothing is committed to your default branch — you merge the PR
              yourself after review.
            </DialogDescription>
          </DialogHeader>
          {lowConfidence && (
            <p className="rounded-md border border-severity-medium/30 bg-severity-medium/5 px-3 py-2 text-sm">
              This fix scored {Math.round(proposal.confidence_score)}% confidence, below the{" "}
              {CONFIDENCE_THRESHOLD}% auto-approve bar. By creating the PR you&apos;re approving it manually —
              the diff above is what will be pushed.
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmPr(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setConfirmPr(false);
                approve.mutate();
              }}
              disabled={approve.isPending}
            >
              <GitPullRequest /> Create PR
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

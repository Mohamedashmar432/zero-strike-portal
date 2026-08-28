"use client";

/**
 * The approve / dismiss / dependency-bump actions for one proposal, extracted so the (scan-page)
 * FixProposalCard and the (workspace) FixProposalDetail share ONE implementation of the write path.
 * Duplicating the approve mutation would mean two places to get the confirm-before-PR wording,
 * the confidence warning, and the disabled states right.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, GitPullRequest, MessageSquare, Package, Sparkles, Wand2, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
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

/**
 * Fallback only, for the brief window before the scan's auto-fix payload has loaded.
 *
 * The effective bar is admin-configurable (RemediationSettings) and arrives on
 * `AutoFixSummary.confidence_threshold`, which every project member can read. Do NOT fetch
 * /remediation-settings here: it is `require_admin`, so a plain project owner — who *can* approve a
 * fix — gets a 403 and would silently see this fallback instead of the real policy in the approval
 * dialog. Taking it from the summary also means the client can never disagree with the server about
 * which bucket a proposal is in.
 */
export const FALLBACK_THRESHOLD = 80;

export function confidenceTone(score: number, threshold = FALLBACK_THRESHOLD): string {
  if (score >= threshold) return "text-status-success";
  if (score >= threshold / 2) return "text-severity-medium";
  return "text-muted-foreground";
}

/** What a reviewer is allowed to do with this proposal right now. Derived in one place so the card
 * and the detail pane can never disagree about whether a button should be shown. */
export function fixCapabilities(proposal: AiFixProposal, canApprove: boolean) {
  const rs = proposal.review_state;
  const hasPatch = !!(proposal.original_code && proposal.patched_code);
  const manualReason =
    rs === "manual_review" && proposal.manual_review_reason ? proposal.manual_review_reason : null;
  return {
    hasPatch,
    manualReason,
    inFlight: rs === "approved" || rs === "applying",
    canDismiss: rs !== "dismissed" && rs !== "pr_open",
    canRevise: rs === "proposed" || rs === "manual_review" || rs === "validated" || rs === "failed",
    // A human owner/admin can create the PR for any reviewable proposal that has a patch —
    // confidence only gates *auto*-approval, not a human who has read the diff. The apply job still
    // re-scans and refuses to push anything that introduces new findings.
    canCreatePr:
      canApprove && proposal.can_fix && hasPatch && (rs === "proposed" || rs === "validated" || rs === "failed"),
    // manual_review means the write already failed (e.g. no connected repo) — show it disabled with why.
    prBlocked:
      canApprove && proposal.can_fix && hasPatch && rs === "manual_review"
        ? manualReason ?? "Needs manual review."
        : null,
  };
}

/**
 * Which proposals a reviewer may put in a batch PR. Mirrors the backend's `_APPROVABLE_STATES`:
 * everything with a patch that hasn't already shipped or started a write. Kept next to
 * fixCapabilities so the row checkbox and the per-fix Create PR button can't disagree about
 * what is approvable.
 */
const BATCHABLE_STATES = ["proposed", "validated", "failed", "manual_review"];

export function canBatchApprove(proposal: AiFixProposal, canApprove: boolean): boolean {
  return (
    canApprove &&
    proposal.can_fix &&
    !!(proposal.original_code && proposal.patched_code) &&
    BATCHABLE_STATES.includes(proposal.review_state)
  );
}

/** SCA version picker: AI recommends the safe version (preselected); choosing another re-runs the
 * fix agent to regenerate the manifest bump. Scanner SCA data only — no registry calls. */
export function DependencyUpdatePicker({
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

/** The primary PR button + its confirm dialog. */
export function CreatePrButton({
  proposal,
  canApprove,
  invalidateKey,
  threshold = FALLBACK_THRESHOLD,
  size = "sm",
  className,
}: {
  proposal: AiFixProposal;
  canApprove: boolean;
  invalidateKey: readonly unknown[];
  /** Effective bar from AutoFixSummary.confidence_threshold — see FALLBACK_THRESHOLD. */
  threshold?: number;
  size?: "sm" | "default";
  className?: string;
}) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);
  const caps = fixCapabilities(proposal, canApprove);

  const approve = useMutation({
    mutationFn: () => approveFixProposal(proposal.id),
    onSuccess: () => {
      toast.success("Approved — creating the pull request…");
      qc.invalidateQueries({ queryKey: invalidateKey });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Something went wrong"),
  });

  const lowConfidence = proposal.confidence_score < threshold;

  if (proposal.pr_url) {
    return (
      <Button
        size={size}
        variant="outline"
        className={cn("shrink-0", className)}
        onClick={() => window.open(proposal.pr_url!, "_blank", "noopener,noreferrer")}
      >
        <GitPullRequest /> View PR <ExternalLink />
      </Button>
    );
  }
  if (caps.inFlight || approve.isPending) {
    return (
      <Button size={size} className={cn("shrink-0", className)} disabled>
        <GitPullRequest /> Applying…
      </Button>
    );
  }
  if (caps.prBlocked) {
    return (
      <Button size={size} variant="outline" className={cn("shrink-0", className)} disabled title={caps.prBlocked}>
        <GitPullRequest /> Create PR
      </Button>
    );
  }
  if (!caps.canCreatePr) return null;

  return (
    <>
      <Button size={size} className={cn("shrink-0", className)} onClick={() => setConfirm(true)}>
        <GitPullRequest /> Create PR
      </Button>
      <Dialog open={confirm} onOpenChange={setConfirm}>
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
              This fix scored {Math.round(proposal.confidence_score)}% confidence, below the {threshold}%
              auto-approve bar. By creating the PR you&apos;re approving it manually — the diff shown is what
              will be pushed.
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                setConfirm(false);
                approve.mutate();
              }}
              disabled={approve.isPending}
            >
              <GitPullRequest /> Create PR
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** Secondary actions row: Ask AI toggle, comments, dismiss. */
export function FixSecondaryActions({
  proposal,
  invalidateKey,
  commentCount = 0,
  askOpen,
  onToggleAsk,
  onOpenComments,
}: {
  proposal: AiFixProposal;
  invalidateKey: readonly unknown[];
  commentCount?: number;
  askOpen: boolean;
  onToggleAsk: () => void;
  onOpenComments: (findingId: string) => void;
}) {
  const qc = useQueryClient();
  const caps = fixCapabilities(proposal, false);
  const dismiss = useMutation({
    mutationFn: () => dismissFixProposal(proposal.id),
    onSuccess: () => {
      toast.success("Proposal dismissed");
      qc.invalidateQueries({ queryKey: invalidateKey });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Something went wrong"),
  });

  return (
    <div className="flex items-center gap-2">
      {proposal.review_state !== "dismissed" && (
        <Button size="sm" variant={askOpen ? "secondary" : "outline"} onClick={onToggleAsk}>
          <Sparkles /> Ask AI
        </Button>
      )}
      <Button size="sm" variant="outline" onClick={() => onOpenComments(proposal.finding_id)}>
        <MessageSquare /> Comments{commentCount ? ` (${commentCount})` : ""}
      </Button>
      {caps.canDismiss && (
        <Button
          size="sm"
          variant="ghost"
          className="ml-auto text-muted-foreground"
          onClick={() => dismiss.mutate()}
          disabled={dismiss.isPending}
        >
          <X /> Dismiss
        </Button>
      )}
    </div>
  );
}

"use client";

/**
 * The batch action bar: turn a multi-selection of proposals into ONE pull request.
 *
 * The flaw this exists for: proposal granularity was also PR granularity, so approving a scan's
 * 40 fixes meant 40 branches and 40 review threads. Per-finding proposals stay exactly as they
 * were — only the write is batched. See docs/AUTOFIX_BATCH_PR.md.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { GitPullRequest, X } from "lucide-react";
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
import { type AiFixProposal, approveFixBatch } from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";

/**
 * The toast's "what got left out" line. Exported so it can be tested: the only way to see it in a
 * browser is to approve a real batch, which opens a real pull request.
 *
 * Every reason with its count, not just the first — a reviewer who ticked 12 boxes and got 9 queued
 * needs all three reasons, and skips are a race (a PR opened meanwhile, another write in flight) so
 * they arrive mixed. Returns null when nothing was skipped, which is the common case.
 */
export function summarizeSkipped(skipped: readonly { reason: string }[]): string | null {
  if (!skipped.length) return null;
  const byReason = new Map<string, number>();
  for (const s of skipped) byReason.set(s.reason, (byReason.get(s.reason) ?? 0) + 1);
  const reasons = Array.from(byReason, ([reason, count]) => `${count} × ${reason}`).join(" ");
  return `${skipped.length} left out — ${reasons}`;
}

export function BatchApproveBar({
  scanId,
  selected,
  onClear,
  invalidateKey,
}: {
  scanId: string;
  /** The selected proposals, already filtered to the batch-approvable ones. */
  selected: AiFixProposal[];
  onClear: () => void;
  invalidateKey: readonly unknown[];
}) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState(false);

  const files = Array.from(new Set(selected.map((p) => p.file_path ?? p.finding_file).filter(Boolean))) as string[];

  const approve = useMutation({
    mutationFn: () => approveFixBatch(scanId, { proposal_ids: selected.map((p) => p.id) }),
    onSuccess: (res) => {
      const n = res.approved.length;
      const description = summarizeSkipped(res.skipped);
      toast.success(
        `Approved ${n} fix${n === 1 ? "" : "es"} — creating one pull request…`,
        description ? { description } : undefined
      );
      setConfirm(false);
      onClear();
      qc.invalidateQueries({ queryKey: invalidateKey });
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Something went wrong"),
  });

  if (!selected.length) return null;

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-brand/40 bg-brand/5 px-3 py-2">
        <span className="text-sm font-medium">
          {selected.length} fix{selected.length === 1 ? "" : "es"} selected
        </span>
        <span className="text-sm text-muted-foreground">
          {files.length} file{files.length === 1 ? "" : "s"}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" variant="ghost" onClick={onClear}>
            <X /> Clear
          </Button>
          <Button size="sm" onClick={() => setConfirm(true)} disabled={approve.isPending}>
            <GitPullRequest /> {approve.isPending ? "Creating…" : "Create one PR"}
          </Button>
        </div>
      </div>

      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              Create one pull request for {selected.length} fix{selected.length === 1 ? "" : "es"}?
            </DialogTitle>
            <DialogDescription>
              ZeroStrike pushes a single branch with all {selected.length} patches and opens one pull
              request against the connected repository. Nothing is committed to your default branch — you
              merge the PR yourself after review.
            </DialogDescription>
          </DialogHeader>
          <ul className="max-h-48 space-y-1 overflow-y-auto rounded-md border bg-muted/20 p-2 font-mono text-xs">
            {files.map((f) => (
              <li key={f} className="truncate">
                {f}
              </li>
            ))}
          </ul>
          {/* The apply job re-scans the combined diff. Saying so up front is what makes a partial
              result readable later instead of looking like a silent failure. */}
          <p className="rounded-md border border-severity-medium/30 bg-severity-medium/5 px-3 py-2 text-sm">
            Each patch is re-scanned before the PR is opened. Any fix that fails that check is left out of
            the PR and sent back for manual review — it does not block the others.
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Cancel
            </Button>
            <Button onClick={() => approve.mutate()} disabled={approve.isPending}>
              <GitPullRequest /> {approve.isPending ? "Creating…" : "Create pull request"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

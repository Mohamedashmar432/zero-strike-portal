"use client";

import { useMutation } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import {
  bulkUpdateVulnerabilities,
  chunkIds,
  statusChangeBlockReason,
  type BulkAction,
  type BulkItemResult,
  type ResolutionReason,
  type VulnerabilityStatus,
} from "@/lib/api/vulnerabilities";
import { MIN_RISK_COMMENT_CHARS, checkRiskComment } from "@/lib/risk-comment";

const UNASSIGNED = "__unassigned__";
type Choice = "open" | "in_progress" | "resolved" | "accepted_risk" | "false_positive";
const CHOICE_LABELS: Record<Choice, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  accepted_risk: "Accepted risk",
  false_positive: "False positive",
};
const REASONS: { value: ResolutionReason; label: string }[] = [
  { value: "fixed", label: "Fixed" },
  { value: "duplicate", label: "Duplicate" },
  { value: "wont_fix", label: "Won't fix" },
  { value: "not_reproducible", label: "Not reproducible" },
];

export type BulkOutcome = { succeeded: string[]; failed: BulkItemResult[]; awaitingReview: number };

/** Runs a bulk change in API-sized chunks and merges the per-item results. */
async function runBulk(projectId: string, ids: string[], change: BulkAction): Promise<BulkOutcome> {
  const succeeded: string[] = [];
  const failed: BulkItemResult[] = [];
  let awaitingReview = 0;
  for (const chunk of chunkIds(ids)) {
    const res = await bulkUpdateVulnerabilities(projectId, chunk, change);
    for (const r of res.results) {
      if (!r.ok) failed.push(r);
      else {
        succeeded.push(r.id);
        if (r.review_status === "pending") awaitingReview += 1;
      }
    }
  }
  return { succeeded, failed, awaitingReview };
}

export function BulkActionBar({
  projectId,
  selectedIds,
  members,
  nameOf,
  onClear,
  onOutcome,
}: {
  projectId: string;
  selectedIds: string[];
  members: { user_id: string; label: string }[];
  /** Human name for a finding id, for the failure list. */
  nameOf: (id: string) => string;
  onClear: () => void;
  /** Called after every attempt so the page can refresh and trim the selection to what failed. */
  onOutcome: (outcome: BulkOutcome) => void;
}) {
  const [assignee, setAssignee] = useState<string>(UNASSIGNED);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [choice, setChoice] = useState<Choice>("in_progress");
  const [reason, setReason] = useState<ResolutionReason>("duplicate");
  const [comment, setComment] = useState("");
  const [failures, setFailures] = useState<BulkItemResult[]>([]);

  const mutation = useMutation({
    mutationFn: (change: BulkAction) => runBulk(projectId, selectedIds, change),
    onSuccess: (outcome) => {
      setFailures(outcome.failed);
      const ok = outcome.succeeded.length;
      const waiting = outcome.awaitingReview > 0 ? ` ${outcome.awaitingReview} sent to a portal admin for review.` : "";
      if (outcome.failed.length === 0) toast.success(`${ok} finding${ok === 1 ? "" : "s"} processed.${waiting}`);
      else toast.warning(`${ok} updated, ${outcome.failed.length} refused. See the list below.`);
      setDialogOpen(false);
      setComment("");
      onOutcome(outcome);
    },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Bulk update failed"),
  });

  const status: VulnerabilityStatus = choice === "false_positive" ? "resolved" : choice;
  const resolution: ResolutionReason | null =
    choice === "false_positive" ? "false_positive" : choice === "resolved" ? reason : null;
  const needsComment = choice === "accepted_risk" || choice === "false_positive";
  const block = statusChangeBlockReason(status, resolution, comment);
  const risk = checkRiskComment(comment);

  if (selectedIds.length === 0 && failures.length === 0) return null;

  return (
    <section
      aria-label="Bulk actions"
      className="sticky bottom-3 z-20 space-y-2 rounded-lg border border-border bg-card px-3 py-2.5"
    >
      {selectedIds.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="legend text-foreground">{selectedIds.length} selected</span>
          <span className="mx-1 h-4 w-px bg-border" aria-hidden="true" />

          <Label htmlFor="bulk-assignee" className="sr-only">
            Assign to
          </Label>
          <Select value={assignee} onValueChange={(v) => v && setAssignee(v)}>
            <SelectTrigger id="bulk-assignee" size="sm" className="w-52 text-xs">
              <SelectValue>
                {assignee === UNASSIGNED ? "Unassigned" : (members.find((m) => m.user_id === assignee)?.label ?? "Member")}
              </SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={UNASSIGNED}>Unassigned</SelectItem>
              {members.map((m) => (
                <SelectItem key={m.user_id} value={m.user_id}>
                  {m.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm"
            variant="outline"
            disabled={mutation.isPending}
            onClick={() =>
              mutation.mutate({ action: "assign", assignee_user_id: assignee === UNASSIGNED ? null : assignee })
            }
          >
            Assign
          </Button>
          <Button size="sm" variant="outline" disabled={mutation.isPending} onClick={() => setDialogOpen(true)}>
            Change status…
          </Button>
          <Button size="sm" variant="ghost" className="ml-auto" onClick={onClear}>
            <X /> Clear selection
          </Button>
        </div>
      )}

      {failures.length > 0 && (
        <div role="alert" className="rounded-sm border-l-2 border-severity-high bg-severity-high-tint px-3 py-2 text-xs">
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium">
              {failures.length} finding{failures.length === 1 ? " was" : "s were"} not changed. They stay selected.
            </p>
            <Button size="xs" variant="ghost" onClick={() => setFailures([])}>
              Dismiss
            </Button>
          </div>
          <ul className="mt-1 max-h-32 space-y-0.5 overflow-y-auto">
            {failures.map((f) => (
              <li key={f.id}>
                <span className="font-semibold">{nameOf(f.id)}</span>
                <span className="text-muted-foreground">: {f.detail ?? "Refused"}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Change status of {selectedIds.length} findings</DialogTitle>
            <DialogDescription>
              Each finding goes through the same rules as a single change. One the rules refuse is listed with the
              reason and the rest still apply. False positives and accepted risk follow the workspace review settings.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="bulk-status">Status</Label>
              <Select value={choice} onValueChange={(v) => v && setChoice(v as Choice)}>
                <SelectTrigger id="bulk-status">
                  <SelectValue>{CHOICE_LABELS[choice]}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(CHOICE_LABELS) as Choice[]).map((c) => (
                    <SelectItem key={c} value={c}>
                      {CHOICE_LABELS[c]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {choice === "resolved" && (
              <div className="space-y-1.5">
                <Label htmlFor="bulk-reason">Resolution reason</Label>
                <Select value={reason} onValueChange={(v) => v && setReason(v as ResolutionReason)}>
                  <SelectTrigger id="bulk-reason">
                    <SelectValue>{REASONS.find((r) => r.value === reason)?.label}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {REASONS.map((r) => (
                      <SelectItem key={r.value} value={r.value}>
                        {r.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            {(needsComment || choice === "resolved") && (
              <div className="space-y-1.5">
                <Label htmlFor="bulk-comment">Comment{needsComment ? " (required)" : " (optional)"}</Label>
                <Textarea
                  id="bulk-comment"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Applied to every selected finding."
                />
                {choice === "accepted_risk" && (
                  <p
                    aria-live="polite"
                    className={`font-mono text-[11px] ${risk.ok ? "text-status-success" : "text-muted-foreground"}`}
                  >
                    {risk.chars}/{MIN_RISK_COMMENT_CHARS} characters · {risk.words}/6 words
                  </p>
                )}
                {block && comment.trim() !== "" && <p className="text-xs text-muted-foreground">{block}</p>}
              </div>
            )}
          </div>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
            <Button
              disabled={block !== null || mutation.isPending}
              onClick={() =>
                mutation.mutate({
                  action: "status",
                  status,
                  resolution_reason: resolution,
                  resolution_comment: comment.trim() || null,
                })
              }
            >
              {mutation.isPending ? "Applying…" : "Apply"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

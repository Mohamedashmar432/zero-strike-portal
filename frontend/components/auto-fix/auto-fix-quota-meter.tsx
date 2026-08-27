"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Gauge } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  getScanAutoFixQuota,
  listScanQuotaRequests,
  requestAutoFixQuota,
} from "@/lib/api/auto-fix-quota";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

/**
 * Per-scan auto-fix allowance, as a compact readout in the section's control row.
 *
 * Deliberately just the number. This is a budget you glance at, not a panel you
 * read — it previously occupied a full-width band above the stats, which gave a
 * secondary constraint more weight than the findings themselves. The detail
 * (remaining, granted extra, last decision, how the allowance works) all lives
 * in the dialog, one click away, which is the only moment any of it matters.
 */
const TONE = {
  ok: "border-border text-muted-foreground hover:border-muted-foreground/50 hover:text-foreground",
  warn: "border-severity-medium/50 bg-severity-medium-tint text-severity-medium hover:border-severity-medium",
  spent: "border-severity-critical/50 bg-severity-critical-tint text-severity-critical hover:border-severity-critical",
} as const;

function toneFor(used: number, limit: number): keyof typeof TONE {
  if (limit <= 0 || used >= limit) return "spent";
  return used / limit >= 0.7 ? "warn" : "ok";
}

export function AutoFixQuotaMeter({ scanId }: { scanId: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("10");
  const [reason, setReason] = useState("");

  const { data: quota, isLoading } = useQuery({
    queryKey: queryKeys.ai.autofix.quota(scanId),
    queryFn: () => getScanAutoFixQuota(scanId),
  });

  const { data: requests } = useQuery({
    queryKey: queryKeys.ai.autofix.quotaRequests(scanId),
    queryFn: () => listScanQuotaRequests(scanId),
  });

  const submit = useMutation({
    mutationFn: () =>
      requestAutoFixQuota(scanId, {
        requested_additional: Number(amount),
        reason: reason.trim(),
      }),
    onSuccess: () => {
      toast.success("Request sent to an administrator for review.");
      setOpen(false);
      setReason("");
      qc.invalidateQueries({ queryKey: queryKeys.ai.autofix.quota(scanId) });
      qc.invalidateQueries({ queryKey: queryKeys.ai.autofix.quotaRequests(scanId) });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not send the request."),
  });

  if (isLoading) return <Skeleton className="h-8 w-20" />;
  if (!quota) return null;

  const tone = toneFor(quota.used, quota.limit);
  const hasPending = quota.pending_request_count > 0;
  const lastDecided = requests?.items.find((r) => r.status !== "pending");

  const amountNum = Number(amount);
  const amountValid = Number.isInteger(amountNum) && amountNum >= 1 && amountNum <= 500;
  const canSubmit = amountValid && reason.trim().length > 0 && !submit.isPending;

  const hint = hasPending
    ? `Auto-fix allowance: ${quota.used} of ${quota.limit} used. A request for more is awaiting review.`
    : quota.remaining > 0
      ? `Auto-fix allowance: ${quota.used} of ${quota.limit} used on this scan, ${quota.remaining} remaining. Click to request more.`
      : `Auto-fix allowance for this scan is used up (${quota.limit}). Click to request more.`;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={hint}
        aria-label={hint}
        className={cn(
          "inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg border bg-clip-padding px-2 font-mono text-[12px] tabular-nums transition-colors",
          "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring/60",
          TONE[tone]
        )}
      >
        <Gauge className="size-3.5" aria-hidden="true" />
        <span className="font-semibold">
          {quota.used}
          <span className="opacity-60">/{quota.limit}</span>
        </span>
        {hasPending && <Clock className="size-3 shrink-0" aria-hidden="true" />}
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Auto-fix allowance</DialogTitle>
            <DialogDescription>
              This scan has fixed {quota.used} of {quota.limit} permitted findings
              {quota.extra_granted > 0
                ? ` (${quota.default_limit} standard, +${quota.extra_granted} granted)`
                : ""}
              . Re-running a fix on a finding you already fixed is free. Each new scan of this
              repository starts with a fresh allowance of {quota.default_limit}.
            </DialogDescription>
          </DialogHeader>

          {hasPending ? (
            <p className="rounded-sm border-l-2 border-severity-medium bg-severity-medium-tint px-3 py-2 text-[13px] text-severity-medium">
              A request for this scan is already awaiting review. You&apos;ll see the new
              allowance here once it&apos;s decided.
            </p>
          ) : (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="quota-amount" className="legend text-muted-foreground">
                  Additional findings needed
                </Label>
                <Input
                  id="quota-amount"
                  type="number"
                  min={1}
                  max={500}
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  aria-invalid={!amountValid}
                />
                {!amountValid && (
                  <p className="font-mono text-[11px] text-destructive">
                    Enter a whole number between 1 and 500.
                  </p>
                )}
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="quota-reason" className="legend text-muted-foreground">
                  Purpose
                </Label>
                <Textarea
                  id="quota-reason"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="What are you remediating, and why does it need more than the standard allowance?"
                />
                <p className="text-[11px] text-muted-foreground">
                  Required. Approving extra allowance authorises additional AI spend, so the
                  reviewer needs to know what it is for.
                </p>
              </div>
            </div>
          )}

          {lastDecided && (
            <p className="border-t border-hairline pt-3 text-[11px] leading-relaxed text-muted-foreground">
              Last decision:{" "}
              <span
                className={
                  lastDecided.status === "approved"
                    ? "text-status-success"
                    : "text-severity-critical"
                }
              >
                {lastDecided.status}
              </span>
              {lastDecided.granted_additional ? ` (+${lastDecided.granted_additional})` : ""}
              {lastDecided.decision_note ? ` — “${lastDecided.decision_note}”` : ""}
            </p>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {hasPending ? "Close" : "Cancel"}
            </Button>
            {!hasPending && (
              <Button disabled={!canSubmit} onClick={() => submit.mutate()}>
                {submit.isPending ? "Sending…" : "Send request"}
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

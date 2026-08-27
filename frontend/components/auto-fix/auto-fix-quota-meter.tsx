"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, Gauge, ShieldCheck } from "lucide-react";
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
 * Per-scan auto-fix allowance, shown at the top of the Auto-Fix section.
 *
 * Reads as an instrument gauge rather than a billing banner: a mono readout, a
 * segmented bar, and a tone that escalates as the budget is consumed. The whole
 * thing is one button — clicking it opens the request dialog — because the moment
 * you care about the number is the moment you have run out.
 */
const TONE = {
  ok: { text: "text-foreground", bar: "bg-status-success", edge: "border-l-status-success" },
  warn: { text: "text-severity-medium", bar: "bg-severity-medium", edge: "border-l-severity-medium" },
  spent: { text: "text-severity-critical", bar: "bg-severity-critical", edge: "border-l-severity-critical" },
} as const;

function toneFor(used: number, limit: number) {
  if (limit <= 0 || used >= limit) return TONE.spent;
  return used / limit >= 0.7 ? TONE.warn : TONE.ok;
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

  if (isLoading) return <Skeleton className="h-[74px] w-full" />;
  if (!quota) return null;

  const tone = toneFor(quota.used, quota.limit);
  const pct = quota.limit > 0 ? Math.min(100, (quota.used / quota.limit) * 100) : 100;
  const hasPending = quota.pending_request_count > 0;
  const lastDecided = requests?.items.find((r) => r.status !== "pending");

  const amountNum = Number(amount);
  const amountValid = Number.isInteger(amountNum) && amountNum >= 1 && amountNum <= 500;
  const canSubmit = amountValid && reason.trim().length > 0 && !submit.isPending;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Auto-fix allowance for this scan — request more"
        className={cn(
          "group w-full cursor-pointer rounded-lg border border-border border-l-2 bg-card px-4 py-3 text-left transition-colors",
          "hover:border-muted-foreground/40 focus-visible:outline-2 focus-visible:outline-ring/60",
          tone.edge
        )}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <span className="legend flex items-center gap-1.5 text-muted-foreground">
            <Gauge className="size-3.5" aria-hidden="true" />
            Auto-Fix allowance · this scan
          </span>
          <span className="legend text-muted-foreground transition-colors group-hover:text-signal">
            {hasPending ? "Request pending" : "Request more"}
          </span>
        </div>

        <div className="mt-2 flex items-end justify-between gap-4">
          <p className={cn("readout text-2xl leading-none", tone.text)}>
            {quota.used}
            <span className="text-muted-foreground"> / {quota.limit}</span>
            <span className="legend ml-2 text-muted-foreground">findings fixed</span>
          </p>
          {hasPending && (
            <span className="legend flex items-center gap-1.5 rounded-sm bg-severity-medium-tint px-1.5 py-0.5 text-severity-medium">
              <Clock className="size-3" aria-hidden="true" />
              Awaiting review
            </span>
          )}
          {!hasPending && quota.extra_granted > 0 && (
            <span className="legend flex items-center gap-1.5 rounded-sm bg-status-success-tint px-1.5 py-0.5 text-status-success">
              <ShieldCheck className="size-3" aria-hidden="true" />
              +{quota.extra_granted} granted
            </span>
          )}
        </div>

        <div className="mt-2 h-1.5 w-full overflow-hidden rounded-sm bg-muted">
          <div className={cn("h-full transition-[width] duration-300", tone.bar)} style={{ width: `${pct}%` }} />
        </div>

        <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
          {quota.remaining > 0
            ? `${quota.remaining} more finding${quota.remaining === 1 ? "" : "s"} can be auto-fixed on this scan. Re-running a fix on a finding you already fixed is free.`
            : "This scan's allowance is used up. Request more to keep going — scanning the repo again starts a fresh allowance."}
        </p>
      </button>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Request more auto-fix allowance</DialogTitle>
            <DialogDescription>
              This scan has fixed {quota.used} of {quota.limit} permitted findings. An
              administrator reviews the request, and may grant a different amount than you ask
              for. Each new scan of this repository starts with a fresh allowance of{" "}
              {quota.default_limit}.
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
              <span className={lastDecided.status === "approved" ? "text-status-success" : "text-severity-critical"}>
                {lastDecided.status}
              </span>
              {lastDecided.granted_additional ? ` (+${lastDecided.granted_additional})` : ""}
              {lastDecided.decision_note ? ` — "${lastDecided.decision_note}"` : ""}
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

"use client";

import { Clock } from "lucide-react";
import { useQueuedJob } from "@/components/queue/queue-tag";
import { formatDuration, type QueueKind } from "@/lib/api/operations";
import { cn } from "@/lib/utils";

const SLOT_NOUN: Record<QueueKind, string> = {
  cloud_scan: "cloud scan",
  ai_analysis: "AI analysis",
  remediation: "auto-fix",
  compliance: "compliance audit",
};

/**
 * The detail-page version of the queued tag: "Queued — #2 in line · starts in ~3:41", with what it is
 * waiting on. Renders nothing once the job leaves the queue (the page's own status takes over).
 */
export function QueueNotice({ kind, refId, className }: { kind: QueueKind; refId: string; className?: string }) {
  const info = useQueuedJob(kind, refId);
  if (!info) return null;
  const { job, queue, paused, startAt, countdown } = info;

  return (
    <div
      role="status"
      className={cn("flex items-start gap-2.5 rounded-md border border-border bg-muted/40 px-3 py-2 text-sm", className)}
    >
      <Clock className="mt-0.5 size-4 shrink-0 text-severity-medium" />
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium text-foreground">
          Queued — #{job.position} in line
          {paused ? (
            " · queue paused"
          ) : countdown ? (
            <>
              {" · starts in ~"}
              <span className="font-mono tabular-nums">{countdown}</span>
            </>
          ) : (
            " · should start any moment"
          )}
        </p>
        {paused ? (
          <p className="text-xs text-muted-foreground">
            An admin has set this queue&apos;s limit to 0, so nothing in it starts until that is raised.
          </p>
        ) : (
          queue && (
            <p className="text-xs text-muted-foreground">
              {queue.running} of {queue.capacity} {SLOT_NOUN[kind]} slots busy
              {startAt && countdown ? ` · estimated start ${startAt.toLocaleTimeString()}` : ""} ·{" "}
              {queue.avg_is_default
                ? "rough estimate until more runs finish"
                : `based on a ${formatDuration(queue.avg_duration_seconds)} average run`}
            </p>
          )
        )}
      </div>
    </div>
  );
}

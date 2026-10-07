"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { formatCountdown, getQueue, type QueueJob, type QueueKind, type QueueSummary } from "@/lib/api/operations";
import { queryKeys } from "@/lib/api/query-keys";
import { cn, parseApiDate } from "@/lib/utils";

const POLL_MS = 5000;

/** Re-renders every second while `active`, so a countdown moves between polls. */
function useTick(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [active]);
  return now;
}

/** The shared queue snapshot. Every tag and notice reads the same query, so a list of twenty queued
 *  rows still makes one request every few seconds — and only while something on screen needs it. */
function useQueueView(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.queue(),
    queryFn: getQueue,
    enabled,
    refetchInterval: (query) => (query.state.status === "error" ? false : POLL_MS),
  });
}

export type QueuedJobInfo = {
  job: QueueJob;
  queue: QueueSummary | undefined;
  // A limit of 0 pauses the queue: the backend gives no start time, so none is shown.
  paused: boolean;
  startAt: Date | null;
  // "m:ss" until the estimated start; null once it has passed (show "any moment").
  countdown: string | null;
};

function describe(job: QueueJob, data: { server_time: string; queues: QueueSummary[] }, updatedAt: number, now: number) {
  const queue = data.queues.find((q) => q.kind === job.kind);
  // Count down on the server's clock: a laptop a minute fast would otherwise say "any moment" early.
  const skew = parseApiDate(data.server_time).getTime() - updatedAt;
  const startAt = job.estimated_start_at ? parseApiDate(job.estimated_start_at) : null;
  return {
    job,
    queue,
    paused: queue?.capacity === 0,
    startAt,
    countdown: startAt ? formatCountdown(startAt.getTime() - (now + skew)) : null,
  };
}

/** The queued job behind `refId` (a scan id, an audit id, or a finding fingerprint), or null when it
 *  is not queued — mount freely, it renders nothing for anything that is not waiting. */
export function useQueuedJob(kind: QueueKind, refId: string | null | undefined): QueuedJobInfo | null {
  const { data, dataUpdatedAt } = useQueueView(!!refId);
  const job = data?.jobs.find((j) => j.kind === kind && j.ref_id === refId && j.status === "queued");
  const now = useTick(!!job);
  return data && job ? describe(job, data, dataUpdatedAt, now) : null;
}

/** The earliest queued start among a project's jobs of one kind — for count-only summaries. */
export function useNextQueued(kind: QueueKind, projectId: string | null | undefined): QueuedJobInfo | null {
  const { data, dataUpdatedAt } = useQueueView(!!projectId);
  const next = data?.jobs
    .filter((j) => j.kind === kind && j.project_id === projectId && j.status === "queued")
    .sort((a, b) => (a.position ?? 0) - (b.position ?? 0))[0];
  const now = useTick(!!next);
  return data && next ? describe(next, data, dataUpdatedAt, now) : null;
}

/** "#2 · 1:23" / "#2 · any moment" / "#2 · paused" — the part every queued tag adds. */
export function queueTagText(info: QueuedJobInfo): string {
  const when = info.paused ? "paused" : info.countdown ? info.countdown : "any moment";
  return `#${info.job.position} · ${when}`;
}

function tooltip(info: QueuedJobInfo): string {
  if (info.paused) return "This queue is paused (limit 0) — nothing in it starts until an admin raises the limit.";
  const at = info.startAt && info.countdown ? `, estimated start ${info.startAt.toLocaleTimeString()}` : "";
  return `Position ${info.job.position} in the ${info.queue?.label.toLowerCase() ?? "queue"}${at}. An estimate from recent runs.`;
}

/**
 * The queued suffix inside an existing status badge (`inline`), or a self-contained "QUEUED #2 · 1:23"
 * pill (`standalone`) for places with no badge of their own. Renders nothing unless the job is queued.
 */
export function QueueTag({
  kind,
  refId,
  standalone = false,
  className,
}: {
  kind: QueueKind;
  refId: string | null | undefined;
  standalone?: boolean;
  className?: string;
}) {
  const info = useQueuedJob(kind, refId);
  if (!info) return null;
  return <QueueTagView info={info} standalone={standalone} className={className} />;
}

export function QueueTagView({
  info,
  standalone = false,
  prefix = "",
  className,
}: {
  info: QueuedJobInfo;
  standalone?: boolean;
  prefix?: string;
  className?: string;
}) {
  const text = queueTagText(info);
  if (standalone) {
    return (
      <span
        title={tooltip(info)}
        className={cn(
          "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-mono text-[11px] font-semibold uppercase",
          "bg-severity-medium/15 text-severity-medium",
          className
        )}
      >
        Queued <span className="normal-case tabular-nums">{text}</span>
      </span>
    );
  }
  return (
    <span title={tooltip(info)} className={cn("normal-case tabular-nums opacity-90", className)}>
      · {prefix}
      {text}
    </span>
  );
}

/** For count-only summaries ("2 QUEUED"): adds when the project's next queued job should start. */
export function NextQueuedTag({ kind, projectId }: { kind: QueueKind; projectId: string | null | undefined }) {
  const info = useNextQueued(kind, projectId);
  return info ? <QueueTagView info={info} prefix="next " /> : null;
}

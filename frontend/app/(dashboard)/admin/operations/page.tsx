"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Gauge, Layers, ListOrdered } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  formatBytes,
  formatCountdown,
  formatDuration,
  getOperations,
  type QueueJob,
  type QueueKind,
} from "@/lib/api/operations";
import { queryKeys } from "@/lib/api/query-keys";
import { cn, parseApiDate } from "@/lib/utils";

const POLL_MS = 3000;

const QUEUE_LABEL: Record<QueueKind, string> = {
  cloud_scan: "Cloud scan",
  ai_analysis: "AI analysis",
  remediation: "Auto-fix",
  compliance: "Compliance",
};

/** Where a job's own page lives — the scan for scan-bound work, the audit for compliance. */
function jobHref(job: QueueJob): string {
  if (job.kind === "compliance") return `/projects/${job.project_id}/compliance/${job.ref_id}`;
  // A single-finding AI job is keyed on the finding's fingerprint, which has no page of its own.
  if (job.kind === "ai_analysis" && !/^[a-f0-9]{24}$/.test(job.ref_id)) return `/projects/${job.project_id}`;
  return `/projects/${job.project_id}/scans/${job.ref_id}`;
}

// A job can outlive its project; a link to a deleted project could only 404.
function ProjectLink({ job }: { job: QueueJob }) {
  if (!job.project_name) return <span className="text-muted-foreground">Deleted project</span>;
  return (
    <Link href={`/projects/${job.project_id}`} className="hover:underline">
      {job.project_name}
    </Link>
  );
}

function Meter({ label, percent, detail }: { label: string; percent: number | null; detail: string }) {
  const pct = Math.min(Math.max(percent ?? 0, 0), 100);
  const tone = pct >= 90 ? "bg-destructive" : pct >= 70 ? "bg-severity-medium" : "bg-primary";
  return (
    <div className="space-y-2 rounded-xl border border-border/70 bg-card/40 p-4">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">{label}</span>
        <span className="font-mono text-lg font-semibold tabular-nums text-foreground">
          {percent == null ? "—" : `${pct.toFixed(0)}%`}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        className="h-2 w-full overflow-hidden rounded-full bg-muted"
      >
        <div className={cn("h-full rounded-full transition-[width] duration-500", tone)} style={{ width: `${pct}%` }} />
      </div>
      <p className="truncate text-xs text-muted-foreground">{detail}</p>
    </div>
  );
}

function Section({ icon: Icon, title, children }: { icon: typeof Gauge; title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2 border-b border-border/60 pb-2">
        <Icon className="size-4 text-muted-foreground" />
        <h2 className="text-sm font-semibold tracking-tight text-foreground">{title}</h2>
      </div>
      {children}
    </div>
  );
}

function elapsed(fromIso: string | null, nowMs: number): string {
  if (!fromIso) return "—";
  return formatDuration(Math.max(0, (nowMs - parseApiDate(fromIso).getTime()) / 1000));
}

export default function OperationsPage() {
  const { data, isLoading, isError, dataUpdatedAt } = useQuery({
    queryKey: queryKeys.admin.operations(),
    queryFn: getOperations,
    // A forbidden or broken endpoint must not be re-asked every 3s.
    refetchInterval: (query) => (query.state.status === "error" ? false : POLL_MS),
  });

  // Ticks every second so countdowns and elapsed times move between polls.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);
  // Everything is measured on the server's clock, not this browser's.
  const serverNow = data ? now + (parseApiDate(data.server_time).getTime() - dataUpdatedAt) : now;

  const sys = data?.system;
  const running = data?.jobs.filter((j) => j.status === "running") ?? [];
  const queued = data?.jobs.filter((j) => j.status === "queued") ?? [];
  const pausedKinds = new Set(data?.queues.filter((q) => q.capacity === 0).map((q) => q.kind));

  return (
    <div className="space-y-6">
      <PageHeader
        title="Operations"
        description="Live load on this backend instance: what is running, what is waiting and when it should start, and what failed in the last 24 hours."
        actions={
          data && (
            <span className="flex items-center gap-2 text-xs text-muted-foreground">
              <span className="relative flex size-2">
                <span className="absolute inline-flex size-full animate-ping rounded-full bg-primary/60" />
                <span className="relative inline-flex size-2 rounded-full bg-primary" />
              </span>
              Live · every {POLL_MS / 1000}s
            </span>
          )
        }
      />

      <Section icon={Gauge} title="Container load">
        {isError ? (
          <p className="text-sm text-destructive">Could not load operations data.</p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Meter
                label="CPU"
                percent={sys ? sys.cpu_percent : null}
                detail={sys ? `of ${sys.cpu_cores} core${sys.cpu_cores === 1 ? "" : "s"}` : isLoading ? "Loading…" : ""}
              />
              <Meter
                label="Memory"
                percent={sys?.memory_percent ?? null}
                detail={sys ? `${formatBytes(sys.memory_used_bytes)} of ${formatBytes(sys.memory_limit_bytes)}` : ""}
              />
              <Meter
                label="Clone disk"
                percent={sys?.disk_total_bytes ? (100 * (sys.disk_used_bytes ?? 0)) / sys.disk_total_bytes : null}
                detail={sys ? `${formatBytes(sys.disk_used_bytes)} of ${formatBytes(sys.disk_total_bytes)}` : ""}
              />
              <div className="space-y-1 rounded-xl border border-border/70 bg-card/40 p-4">
                <span className="text-xs font-medium tracking-wide text-muted-foreground uppercase">Processes</span>
                <p className="font-mono text-lg font-semibold text-foreground">
                  {sys ? `1 + ${sys.subprocess_count}` : "—"}
                </p>
                <p className="text-xs text-muted-foreground">
                  {sys
                    ? `backend ${formatBytes(sys.process_rss_bytes)} · git/scanner ${formatBytes(sys.subprocess_rss_bytes)}`
                    : ""}
                </p>
              </div>
            </div>
            {sys && (
              <p className="text-xs text-muted-foreground">
                {sys.source === "cgroup"
                  ? "Measured against this container's own CPU and memory limits."
                  : "No container limits found — showing the whole machine (typical for local development)."}{" "}
                Figures are for the instance that answered this request.
              </p>
            )}
          </>
        )}
      </Section>

      <Section icon={Layers} title="Queues">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(data?.queues ?? []).map((q) => (
            <div key={q.kind} className="space-y-2 rounded-xl border border-border/70 bg-card/40 p-4">
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-semibold text-foreground">{q.label}</span>
                <span className="font-mono text-xs text-muted-foreground">
                  {q.running} / {q.capacity} running
                </span>
              </div>
              <div className="flex gap-1" aria-label={`${q.running} of ${q.capacity} slots busy`}>
                {Array.from({ length: Math.max(q.capacity, q.running) }, (_, i) => (
                  <div
                    key={i}
                    className={cn(
                      "h-2 flex-1 rounded-full",
                      i < q.running ? (i >= q.capacity ? "bg-destructive" : "bg-primary") : "bg-muted"
                    )}
                  />
                ))}
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
                <span className={cn(q.queued > 0 && "font-medium text-severity-medium")}>{q.queued} queued</span>
                {q.capacity === 0 && <span className="font-medium text-destructive">paused — limit is 0</span>}
                <span>
                  avg run {formatDuration(q.avg_duration_seconds)}
                  {q.avg_is_default ? " (guess)" : ""}
                </span>
                {q.oldest_queued_at && <span>oldest waiting {elapsed(q.oldest_queued_at, serverNow)}</span>}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section icon={ListOrdered} title={`Active work (${running.length} running, ${queued.length} queued)`}>
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load active work."
          isEmpty={!!data && data.jobs.length === 0}
          emptyState={<EmptyState title="Nothing running or queued right now." />}
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">Status</TableHead>
                <TableHead className="py-2.5">Queue</TableHead>
                <TableHead className="py-2.5">Project</TableHead>
                <TableHead className="py-2.5">Job</TableHead>
                <TableHead className="py-2.5">Timing</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[...running, ...queued].map((j) => {
                const startIn =
                  j.estimated_start_at && formatCountdown(parseApiDate(j.estimated_start_at).getTime() - serverNow);
                return (
                  <TableRow key={`${j.kind}-${j.job_id}`} className="text-xs">
                    <TableCell>
                      {j.status === "running" ? (
                        <Badge variant="secondary" className="font-mono text-[10px] text-primary">
                          RUNNING
                        </Badge>
                      ) : (
                        <Badge variant="secondary" className="font-mono text-[10px] text-severity-medium">
                          QUEUED #{j.position}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">{QUEUE_LABEL[j.kind]}</TableCell>
                    <TableCell>
                      <ProjectLink job={j} />
                    </TableCell>
                    <TableCell className="max-w-72 truncate">
                      {j.project_name ? (
                        <Link href={jobHref(j)} className="hover:underline">
                          {j.summary}
                        </Link>
                      ) : (
                        j.summary
                      )}
                      {j.stage && <span className="ml-1.5 text-muted-foreground">· {j.stage}</span>}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground tabular-nums">
                      {j.status === "running"
                        ? `running ${elapsed(j.started_at, serverNow)}`
                        : pausedKinds.has(j.kind)
                          ? "paused (limit 0)"
                          : startIn
                            ? `starts in ~${startIn}`
                            : "starting any moment"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </DataTableCard>
      </Section>

      <Section icon={AlertTriangle} title="Failures in the last 24 hours">
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load recent failures."
          isEmpty={!!data && data.recent_failures.length === 0}
          emptyState={<EmptyState title="No failures in the last 24 hours." />}
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">When</TableHead>
                <TableHead className="py-2.5">Queue</TableHead>
                <TableHead className="py-2.5">Project</TableHead>
                <TableHead className="py-2.5">Job</TableHead>
                <TableHead className="py-2.5">Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.recent_failures.map((f) => (
                <TableRow key={`${f.kind}-${f.job_id}`} className="align-top text-xs">
                  <TableCell className="whitespace-nowrap font-mono text-muted-foreground">
                    {f.completed_at ? parseApiDate(f.completed_at).toLocaleString() : "—"}
                  </TableCell>
                  <TableCell className="text-muted-foreground">{QUEUE_LABEL[f.kind]}</TableCell>
                  <TableCell>
                    <ProjectLink job={f} />
                  </TableCell>
                  <TableCell className="max-w-56 truncate">
                    {f.project_name ? (
                      <Link href={jobHref(f)} className="hover:underline">
                        {f.summary}
                      </Link>
                    ) : (
                      f.summary
                    )}
                    {f.stage && <span className="block text-muted-foreground">failed while {f.stage}</span>}
                  </TableCell>
                  <TableCell className="max-w-md text-destructive whitespace-pre-wrap break-words">
                    {f.error_message || "No error message was recorded."}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </Section>
    </div>
  );
}

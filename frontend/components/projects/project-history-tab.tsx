"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { getProjectScanActivity, type ProjectScanActivity, type ScanHistoryItem } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/common/empty-state";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { SeverityCountPills } from "@/components/severity/severity-count-pills";
import { formatRelativeTime, parseApiDate } from "@/lib/utils";

const ALL = "__all__";

const chartConfig: ChartConfig = {
  total: { label: "Findings", color: "var(--primary)" },
};

// One scan flattened out of its repo group, tagged with the repo it belongs to (the timeline is
// chronological across all repos, so each row carries its own repo label).
type FlatScan = ScanHistoryItem & { repoId: string; repoLabel: string };

function flatten(activity: ProjectScanActivity): FlatScan[] {
  return activity.repos
    .flatMap((g) => g.scans.map((s) => ({ ...s, repoId: g.repo_id ?? "", repoLabel: g.repo_label })))
    .sort((a, b) => parseApiDate(b.created_at).getTime() - parseApiDate(a.created_at).getTime());
}

function monthKey(iso: string) {
  const d = parseApiDate(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}
function monthLabel(iso: string) {
  return parseApiDate(iso).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

// Trend series for the selected repo scope (or all repos), oldest -> newest.
function trendData(scans: FlatScan[]) {
  return [...scans]
    .filter((s) => s.status === "completed")
    .sort((a, b) => parseApiDate(a.created_at).getTime() - parseApiDate(b.created_at).getTime())
    .map((s) => ({
      label: parseApiDate(s.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
      total: s.total_findings,
    }));
}

function ScanRow({ projectId, scan, isLatest }: { projectId: string; scan: FlatScan; isLatest: boolean }) {
  return (
    <li className="relative list-none pb-4 pl-10">
      {/* node sitting on the git-graph line (the line is drawn once, behind, by the timeline) */}
      <span className="absolute left-3 top-5 z-10 size-3 -translate-x-1/2 rounded-full border-2 border-primary bg-background" />
      <Link
        href={`/projects/${projectId}/scans/${scan.scan_id}`}
        className="flex flex-col gap-3 rounded-lg border bg-card p-3 transition-colors hover:border-primary/60 hover:bg-accent md:flex-row md:items-center md:justify-between"
      >
        <div className="min-w-0 space-y-1">
          <div className="text-sm">
            <span className="font-semibold">
              {isLatest ? "Latest, " : ""}
              {formatRelativeTime(scan.created_at)}
            </span>
            <span className="text-muted-foreground">, by {scan.scanned_by || "Unknown"}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-flex items-center rounded-md border bg-background px-2 py-0.5 text-xs font-medium text-foreground">
              {scan.repoLabel}
            </span>
            {scan.status !== "completed" && <ScanStatusBadge status={scan.status} />}
          </div>
        </div>
        <SeverityCountPills counts={scan.findings_by_severity} />
      </Link>
    </li>
  );
}

export function ProjectHistoryTab({ projectId }: { projectId: string }) {
  const { data: activity, isLoading } = useQuery({
    queryKey: queryKeys.projects.scanActivity(projectId),
    queryFn: () => getProjectScanActivity(projectId),
  });
  const [trendScope, setTrendScope] = useState<string>(ALL);
  const [listRepo, setListRepo] = useState<string>(ALL);
  const [listMonth, setListMonth] = useState<string>(ALL);

  const allScans = useMemo(() => (activity ? flatten(activity) : []), [activity]);

  const trendScans = useMemo(
    () => (trendScope === ALL ? allScans : allScans.filter((s) => s.repoId === trendScope)),
    [allScans, trendScope]
  );
  const chartData = useMemo(() => trendData(trendScans), [trendScans]);

  // List: repo-filtered first (so the month options match what's shown), then month-filtered.
  const repoFiltered = useMemo(
    () => (listRepo === ALL ? allScans : allScans.filter((s) => s.repoId === listRepo)),
    [allScans, listRepo]
  );
  const months = useMemo(() => {
    const seen = new Map<string, string>();
    for (const s of repoFiltered) if (!seen.has(monthKey(s.created_at))) seen.set(monthKey(s.created_at), monthLabel(s.created_at));
    return [...seen.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [repoFiltered]);
  const listScans = useMemo(
    () => (listMonth === ALL ? repoFiltered : repoFiltered.filter((s) => monthKey(s.created_at) === listMonth)),
    [repoFiltered, listMonth]
  );

  if (isLoading) return <Skeleton className="h-64 w-full" />;
  if (!activity || activity.repos.length === 0) {
    return <EmptyState title="No scan history" description="Connect a repo and run a scan to build history." />;
  }

  const repoOptions = activity.repos.map((g) => ({ id: g.repo_id ?? "", label: g.repo_label }));
  const labelFor = (id: string) => repoOptions.find((r) => r.id === id)?.label;

  return (
    <div className="space-y-6">
      {/* ---- Trend chart ---- */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <CardTitle className="text-sm font-normal text-muted-foreground">Findings trend</CardTitle>
          <Select value={trendScope} onValueChange={(v) => setTrendScope(v ?? ALL)}>
            <SelectTrigger size="sm" className="w-full sm:w-56">
              <SelectValue>{trendScope === ALL ? "All repositories" : labelFor(trendScope)}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>All repositories</SelectItem>
              {repoOptions.map((r) => (
                <SelectItem key={r.id || "unlinked"} value={r.id}>
                  {r.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </CardHeader>
        <CardContent>
          {chartData.length === 0 ? (
            <EmptyState title="Not enough history yet" description="Run more scans to see a trend." />
          ) : (
            <ChartContainer config={chartConfig} className="h-[240px] w-full">
              <AreaChart data={chartData} margin={{ left: -16, right: 8, top: 8 }}>
                <defs>
                  <linearGradient id="fillTotal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="var(--color-total)" stopOpacity={0.6} />
                    <stop offset="95%" stopColor="var(--color-total)" stopOpacity={0.05} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} />
                <YAxis tickLine={false} axisLine={false} fontSize={12} width={40} allowDecimals={false} />
                <ChartTooltip content={<ChartTooltipContent />} />
                <Area dataKey="total" type="monotone" stroke="var(--color-total)" strokeWidth={2} fill="url(#fillTotal)" />
              </AreaChart>
            </ChartContainer>
          )}
        </CardContent>
      </Card>

      {/* ---- Scan history (git-tree timeline) ---- */}
      <Card>
        <CardHeader className="flex flex-col gap-3 space-y-0 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle className="text-sm font-normal text-muted-foreground">Scan history</CardTitle>
          <div className="flex flex-wrap gap-2">
            <Select value={listRepo} onValueChange={(v) => { setListRepo(v ?? ALL); setListMonth(ALL); }}>
              <SelectTrigger size="sm" className="w-full sm:w-48">
                <SelectValue>{listRepo === ALL ? "All repositories" : labelFor(listRepo)}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All repositories</SelectItem>
                {repoOptions.map((r) => (
                  <SelectItem key={r.id || "unlinked"} value={r.id}>
                    {r.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={listMonth} onValueChange={(v) => setListMonth(v ?? ALL)}>
              <SelectTrigger size="sm" className="w-full sm:w-40">
                <SelectValue>{listMonth === ALL ? "All months" : months.find(([k]) => k === listMonth)?.[1]}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All months</SelectItem>
                {months.map(([key, label]) => (
                  <SelectItem key={key} value={key}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          {listScans.length === 0 ? (
            <EmptyState title="No scans" description="No scans match the selected filters." />
          ) : (
            <ol className="relative">
              {/* the git-graph line: a single vertical rail behind all dots/markers */}
              <span className="absolute bottom-4 left-3 top-2 w-px bg-border" aria-hidden />
              {listScans.map((scan, i) => {
                // A month tag is emitted whenever the month changes going down the list (only in
                // the "All months" view — a single-month filter needs no dividers).
                const showMonth =
                  listMonth === ALL && (i === 0 || monthKey(scan.created_at) !== monthKey(listScans[i - 1].created_at));
                return (
                  <Fragment key={scan.scan_id}>
                    {showMonth && (
                      <li className="relative mb-3 list-none pl-10">
                        <span className="absolute left-3 top-1 z-10 size-2.5 -translate-x-1/2 rounded-full bg-muted-foreground/60 ring-4 ring-background" />
                        <span className="rounded-full bg-muted px-2.5 py-0.5 text-xs font-semibold text-muted-foreground">
                          {monthLabel(scan.created_at)}
                        </span>
                      </li>
                    )}
                    <ScanRow projectId={projectId} scan={scan} isLatest={i === 0} />
                  </Fragment>
                );
              })}
            </ol>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

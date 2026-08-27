"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, FolderGit2, FolderKanban, Plus, Radio, Target } from "lucide-react";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { MetricStrip } from "@/components/common/metric-strip";
import { PageHeader } from "@/components/layout/page-header";
import { SectionRule } from "@/components/layout/section-rule";
import { ProjectRepoBreakdown } from "@/components/projects/project-repo-breakdown";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { refetchWhileAnyRecentScanActive } from "@/lib/api/polling";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import {
  projectRiskStatus,
  SEVERITY_ORDER,
  SeverityCountPills,
} from "@/components/severity/severity-count-pills";
import { SeveritySpectrum } from "@/components/severity/severity-spectrum";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { getDashboardStats, type RecentScanItem, type SeverityCounts } from "@/lib/api/dashboard";
import { listProjects, type Project } from "@/lib/api/projects";

function severityScore(counts: SeverityCounts) {
  return counts.critical * 1000 + counts.high * 100 + counts.medium * 10 + counts.low + counts.info * 0.1;
}

const SEVERITY_DOT: Record<string, string> = {
  critical: "bg-severity-critical",
  high: "bg-severity-high",
  medium: "bg-severity-medium",
  low: "bg-severity-low",
  info: "bg-severity-info",
};

type SortBy = "recent" | "severity" | "status";

/**
 * Total exposure band. The page's hero is the actual severity distribution
 * across the whole workspace — one wide spectrum plus a keyed legend — rather
 * than a row of big numbers. The distribution is the thing a security engineer
 * is trying to read on arrival; the totals are follow-up detail, which is why
 * they sit in the strip *below* this.
 */
function ExposureBand({ counts, isLoading }: { counts?: SeverityCounts; isLoading: boolean }) {
  const empty: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
  const c = counts ?? empty;
  const total = SEVERITY_ORDER.reduce((sum, s) => sum + c[s], 0);

  return (
    <section className="rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="legend text-muted-foreground">Total Exposure</h2>
        {isLoading ? (
          <Skeleton className="h-6 w-20" />
        ) : (
          <p className="readout text-xl leading-none text-foreground">
            {total.toLocaleString()}
            <span className="legend ml-1.5 text-muted-foreground">findings</span>
          </p>
        )}
      </div>

      <div className="mt-3">
        {isLoading ? (
          <Skeleton className="h-2.5 w-full" />
        ) : (
          <SeveritySpectrum counts={c} height="h-2.5" />
        )}
      </div>

      {/* Keyed legend — the spectrum is not the only carrier of the value, so
          the reading survives colorblindness and greyscale printing. */}
      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {SEVERITY_ORDER.map((severity) => (
          <div key={severity} className="flex items-center gap-1.5">
            <span className={cn("size-2 rounded-full", SEVERITY_DOT[severity])} aria-hidden="true" />
            <dt className="legend text-muted-foreground">{severity}</dt>
            <dd className="font-mono text-xs font-semibold tabular-nums text-foreground">
              {isLoading ? "—" : c[severity].toLocaleString()}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: getDashboardStats,
    refetchInterval: refetchWhileAnyRecentScanActive(),
  });

  const { data: projectsPage } = useQuery({
    queryKey: ["projects"],
    queryFn: () => listProjects(),
  });

  const [sortBy, setSortBy] = useState<SortBy>("recent");
  const [expandedScans, setExpandedScans] = useState<Set<string>>(new Set());

  function toggleExpanded(scanId: string) {
    setExpandedScans((prev) => {
      const next = new Set(prev);
      if (next.has(scanId)) next.delete(scanId);
      else next.add(scanId);
      return next;
    });
  }

  const metrics = [
    {
      label: "Total Scans",
      value: (data?.scan_count ?? 0).toLocaleString(),
      hint: "Across all active repositories",
    },
    {
      label: "Projects",
      value: (data?.project_count ?? 0).toLocaleString(),
      hint: "Monitored workspaces",
    },
    {
      label: "Critical",
      value: (data?.findings_by_severity.critical ?? 0).toLocaleString(),
      hint: "Immediate action required",
      tone: "critical" as const,
    },
    {
      label: "High",
      value: (data?.findings_by_severity.high ?? 0).toLocaleString(),
      hint: "Security review needed",
      tone: "high" as const,
    },
  ];

  const focusProjects = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    const focus: { scan: RecentScanItem; project?: Project }[] = [];
    for (const scan of data.recent_scans) {
      if (seen.has(scan.project_id)) continue;
      seen.add(scan.project_id);
      focus.push({ scan, project: projectsPage?.items.find((p) => p.id === scan.project_id) });
      if (focus.length === 3) break;
    }
    return focus;
  }, [data, projectsPage]);

  const sortedScans = useMemo(() => {
    const scans = data?.recent_scans ?? [];
    if (sortBy === "severity") {
      return [...scans].sort((a, b) => severityScore(b.findings_by_severity) - severityScore(a.findings_by_severity));
    }
    if (sortBy === "status") {
      return [...scans].sort((a, b) => a.status.localeCompare(b.status));
    }
    return scans;
  }, [data, sortBy]);

  return (
    // One orchestrated entrance, staggered by --d, instead of scattered
    // micro-animations. Respects prefers-reduced-motion via globals.css.
    <div className="space-y-7">
      <div className="signal-in">
        <PageHeader
          eyebrow="Workspace / Overview"
          title="Security Posture"
          description="Continuous SAST coverage, vulnerability distribution, and live scan activity."
          actions={
            <Button nativeButton={false} render={<Link href="/projects" />} size="lg">
              <Plus className="size-4" />
              Add Project
            </Button>
          }
        />
      </div>

      <div className="signal-in" style={{ "--d": "60ms" } as React.CSSProperties}>
        <ExposureBand counts={data?.findings_by_severity} isLoading={isLoading} />
      </div>

      <div className="signal-in" style={{ "--d": "120ms" } as React.CSSProperties}>
        <MetricStrip metrics={metrics} isLoading={isLoading} />
      </div>

      {/* Focus */}
      <section className="signal-in space-y-3" style={{ "--d": "180ms" } as React.CSSProperties}>
        <SectionRule
          label="Focus"
          icon={Target}
          actions={
            <Link
              href="/projects"
              className="legend text-muted-foreground transition-colors hover:text-signal"
            >
              All projects
            </Link>
          }
        />
        {isLoading ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-32 w-full" />
            ))}
          </div>
        ) : focusProjects.length === 0 ? (
          <EmptyState
            icon={FolderKanban}
            title="No projects yet"
            description="Run a scan on a project and it will surface here."
            className="m-0"
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {focusProjects.map(({ scan, project }) => {
              const risk = projectRiskStatus(scan.findings_by_severity, scan.status);
              return (
                <article
                  key={scan.project_id}
                  className="group flex flex-col gap-3 rounded-lg border border-border bg-card p-4 transition-colors duration-200 hover:border-muted-foreground/40"
                >
                  <div className="flex items-start justify-between gap-2">
                    <Link
                      href={`/projects/${scan.project_id}`}
                      className="min-w-0 truncate font-mono text-[13px] font-bold tracking-[-0.02em] text-foreground transition-colors hover:text-signal"
                    >
                      {scan.project_name}
                    </Link>
                    <span className={cn("shrink-0 rounded-sm px-1.5 py-0.5", risk.className)}>
                      {risk.label}
                    </span>
                  </div>

                  <p className="line-clamp-2 min-h-8 text-xs leading-relaxed text-muted-foreground">
                    {project?.description || "No description."}
                  </p>

                  <div className="mt-auto space-y-2">
                    <SeveritySpectrum counts={scan.findings_by_severity} scanStatus={scan.status} />
                    <SeverityCountPills counts={scan.findings_by_severity} scanStatus={scan.status} />
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {/* Scan operations */}
      <section className="signal-in space-y-3" style={{ "--d": "240ms" } as React.CSSProperties}>
        <SectionRule
          label="Scan Operations"
          icon={Radio}
          actions={
            <Select
              value={sortBy}
              onValueChange={(v) => setSortBy(v as SortBy)}
              items={{
                recent: "Recent activity",
                severity: "Severity (high–low)",
                status: "Status",
              }}
            >
              <SelectTrigger size="sm" aria-label="Sort scan operations" className="h-7 w-40 font-mono text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="recent" className="text-xs">Recent activity</SelectItem>
                <SelectItem value="severity" className="text-xs">Severity (high–low)</SelectItem>
                <SelectItem value="status" className="text-xs">Status</SelectItem>
              </SelectContent>
            </Select>
          }
        />
        <DataTableCard
          isLoading={isLoading}
          isError={false}
          isEmpty={(data?.recent_scans.length ?? 0) === 0}
          emptyState={<EmptyState title="No scans yet" description="Run a scan to see live activity here." />}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                {/* Meter + digital readout, the way an instrument shows one
                    value twice: the bar for scanning a long list, the numbers
                    for acting on a single row. */}
                <TableHead className="w-28">Spectrum</TableHead>
                <TableHead>Findings</TableHead>
                <TableHead>Timestamp</TableHead>
                <TableHead className="w-12">
                  <span className="sr-only">Expand row</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedScans.map((scan: RecentScanItem) => (
                <Fragment key={scan.scan_id}>
                  <TableRow
                    className="cursor-pointer"
                    onClick={() => toggleExpanded(scan.scan_id)}
                    data-expanded={expandedScans.has(scan.scan_id)}
                  >
                    <TableCell>
                      <Link
                        href={`/projects/${scan.project_id}/scans/${scan.scan_id}`}
                        className="font-mono text-[13px] font-semibold text-foreground underline-offset-4 transition-colors hover:text-signal hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {scan.project_name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <ScanTypeBadge scanType={scan.scan_type} />
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-1.5">
                        <ScanStatusBadge status={scan.status} />
                        <AiStatusBadge
                          status={scan.ai_analysis_status}
                          startedAt={scan.ai_analysis_started_at}
                          progressCompleted={scan.ai_analysis_progress_completed}
                          progressTotal={scan.ai_analysis_progress_total}
                        />
                      </div>
                    </TableCell>
                    <TableCell>
                      <SeveritySpectrum counts={scan.findings_by_severity} scanStatus={scan.status} />
                    </TableCell>
                    <TableCell>
                      <SeverityCountPills counts={scan.findings_by_severity} scanStatus={scan.status} />
                    </TableCell>
                    <TableCell className="font-mono text-[11px] text-muted-foreground">
                      {new Date(scan.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <button
                        type="button"
                        aria-expanded={expandedScans.has(scan.scan_id)}
                        aria-label={`${expandedScans.has(scan.scan_id) ? "Hide" : "Show"} repositories for ${scan.project_name}`}
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleExpanded(scan.scan_id);
                        }}
                        className="grid size-7 cursor-pointer place-items-center rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring/60"
                      >
                        <ChevronDown
                          className={cn(
                            "size-3.5 transition-transform duration-200",
                            expandedScans.has(scan.scan_id) && "rotate-180"
                          )}
                          aria-hidden="true"
                        />
                      </button>
                    </TableCell>
                  </TableRow>
                  {expandedScans.has(scan.scan_id) && (
                    <TableRow className="hover:bg-transparent hover:before:opacity-0">
                      <TableCell colSpan={7} className="bg-muted/40 p-0">
                        <div className="space-y-2.5 border-l-2 border-signal/60 p-4 pl-6">
                          <div className="flex items-center gap-2">
                            <FolderGit2 className="size-3.5 text-muted-foreground" aria-hidden="true" />
                            <span className="legend text-muted-foreground">
                              Connected repositories
                            </span>
                          </div>
                          <ProjectRepoBreakdown projectId={scan.project_id} />
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </section>
    </div>
  );
}

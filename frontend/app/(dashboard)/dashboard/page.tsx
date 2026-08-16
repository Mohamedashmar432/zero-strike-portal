"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertOctagon,
  ChevronDown,
  FolderGit2,
  FolderKanban,
  Layers,
  Plus,
  Radio,
  ShieldAlert,
} from "lucide-react";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { StatCard } from "@/components/common/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { ProjectRepoBreakdown } from "@/components/projects/project-repo-breakdown";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { refetchWhileAnyRecentScanActive } from "@/lib/api/polling";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { projectRiskStatus, SeverityCountPills, SEVERITY_PILL_CLASS } from "@/components/severity/severity-count-pills";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { getDashboardStats, type RecentScanItem, type SeverityCounts } from "@/lib/api/dashboard";
import { listProjects, type Project } from "@/lib/api/projects";

function severityScore(counts: SeverityCounts) {
  return counts.critical * 1000 + counts.high * 100 + counts.medium * 10 + counts.low + counts.info * 0.1;
}

type SortBy = "recent" | "severity" | "status";

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

  const stats = [
    {
      label: "Total Scans",
      value: data?.scan_count ?? 0,
      caption: "Across all active repositories",
    },
    {
      label: "Total Projects",
      value: data?.project_count ?? 0,
      caption: "Monitored organizations",
    },
    {
      label: "Critical Findings",
      value: data?.findings_by_severity.critical ?? 0,
      caption: "Immediate action required",
      pillClassName: SEVERITY_PILL_CLASS.critical,
      valueClassName: "text-severity-critical font-mono font-bold",
    },
    {
      label: "High Findings",
      value: data?.findings_by_severity.high ?? 0,
      caption: "Security review needed",
      pillClassName: SEVERITY_PILL_CLASS.high,
      valueClassName: "text-severity-high font-mono font-bold",
    },
  ];

  const pinnedProjects = useMemo(() => {
    if (!data) return [];
    const seen = new Set<string>();
    const pinned: { scan: RecentScanItem; project?: Project }[] = [];
    for (const scan of data.recent_scans) {
      if (seen.has(scan.project_id)) continue;
      seen.add(scan.project_id);
      pinned.push({ scan, project: projectsPage?.items.find((p) => p.id === scan.project_id) });
      if (pinned.length === 3) break;
    }
    return pinned;
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
    <div className="space-y-6">
      <PageHeader
        title="Security Overview"
        description="Continuous SAST posture, vulnerability telemetry, and scan activity."
        actions={
          <Button nativeButton={false} render={<Link href="/projects" />} size="sm" className="gap-1.5 font-medium">
            <Plus className="size-4" />
            Add Project
          </Button>
        }
      />

      {/* Primary KPI Metrics */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 md:gap-4">
        {stats.map((stat) => (
          <StatCard key={stat.label} isLoading={isLoading} {...stat} />
        ))}
      </div>

      {/* Pinned Projects Section */}
      <section className="space-y-3">
        <div className="flex items-center justify-between border-b border-border/60 pb-2">
          <div className="flex items-center gap-2">
            <Layers className="size-4 text-primary" />
            <h2 className="text-sm font-semibold tracking-tight text-foreground">Pinned Projects</h2>
          </div>
          <Link href="/projects" className="text-xs font-medium text-primary hover:underline">
            Manage Projects →
          </Link>
        </div>
        {isLoading ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-36 w-full rounded-xl" />
            ))}
          </div>
        ) : pinnedProjects.length === 0 ? (
          <Card>
            <EmptyState
              icon={FolderKanban}
              title="No projects yet"
              description="Run a scan on a project to see it featured here."
            />
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {pinnedProjects.map(({ scan, project }) => {
              const risk = projectRiskStatus(scan.findings_by_severity);
              return (
                <Card key={scan.project_id} className="border-border/80 bg-card/60 transition-colors hover:border-border hover:bg-card/90">
                  <CardContent className="flex h-full flex-col justify-between gap-3 p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <FolderKanban className="size-4 shrink-0 text-primary" />
                        <Link
                          href={`/projects/${scan.project_id}`}
                          className="font-semibold text-sm text-foreground truncate hover:text-primary transition-colors"
                        >
                          {scan.project_name}
                        </Link>
                      </div>
                      <span className={cn("rounded-md px-2 py-0.5 text-[11px] font-medium shrink-0", risk.className)}>
                        {risk.label}
                      </span>
                    </div>
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {project?.description || "ZeroStrike SAST project."}
                    </p>
                    <div className="border-t border-border/60 pt-2.5">
                      <SeverityCountPills counts={scan.findings_by_severity} />
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      {/* Recent Scans Activity Section */}
      <section className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-border/60 pb-2">
          <div className="flex items-center gap-2">
            <Radio className="size-4 text-primary" />
            <h2 className="text-sm font-semibold tracking-tight text-foreground">Recent Scan Operations</h2>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Sort by:</span>
            <Select value={sortBy} onValueChange={(v) => setSortBy(v as SortBy)}>
              <SelectTrigger size="sm" className="h-7 w-40 text-xs">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="recent" className="text-xs">Recent Activity</SelectItem>
                <SelectItem value="severity" className="text-xs">Severity (High-Low)</SelectItem>
                <SelectItem value="status" className="text-xs">Status</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DataTableCard
          isLoading={isLoading}
          isError={false}
          isEmpty={(data?.recent_scans.length ?? 0) === 0}
          emptyState={<EmptyState title="No scans yet" description="Run a scan to see live activity here." />}
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">Project</TableHead>
                <TableHead className="py-2.5">Type</TableHead>
                <TableHead className="py-2.5">Status</TableHead>
                <TableHead className="py-2.5">Findings</TableHead>
                <TableHead className="py-2.5">Timestamp</TableHead>
                <TableHead className="w-10 py-2.5" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedScans.map((scan: RecentScanItem) => (
                <Fragment key={scan.scan_id}>
                  <TableRow
                    className="cursor-pointer transition-colors hover:bg-muted/30 text-xs"
                    onClick={() => toggleExpanded(scan.scan_id)}
                  >
                    <TableCell className="font-medium">
                      <Link
                        href={`/projects/${scan.project_id}/scans/${scan.scan_id}`}
                        className="text-foreground hover:text-primary underline-offset-4 hover:underline font-semibold"
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
                      <SeverityCountPills counts={scan.findings_by_severity} showLabel={false} />
                    </TableCell>
                    <TableCell className="font-mono text-[11px] text-muted-foreground whitespace-nowrap">
                      {new Date(scan.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <ChevronDown
                        className={cn(
                          "size-3.5 text-muted-foreground transition-transform duration-150",
                          expandedScans.has(scan.scan_id) && "rotate-180"
                        )}
                      />
                    </TableCell>
                  </TableRow>
                  {expandedScans.has(scan.scan_id) && (
                    <TableRow className="hover:bg-transparent">
                      <TableCell colSpan={6} className="bg-muted/30 p-0 border-b border-border/80">
                        <div className="p-4 pl-8 border-l-2 border-primary/50 space-y-2.5 bg-muted/20">
                          <div className="flex items-center gap-2">
                            <FolderGit2 className="size-3.5 text-primary" />
                            <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase font-mono">
                              Connected Repositories & Security Status
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

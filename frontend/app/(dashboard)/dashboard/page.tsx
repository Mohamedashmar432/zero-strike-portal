"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, FolderKanban, Plus } from "lucide-react";
import Link from "next/link";
import { Fragment, useMemo, useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { ProjectRepoBreakdown } from "@/components/projects/project-repo-breakdown";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { projectRiskStatus, SeverityCountPills, SEVERITY_PILL_CLASS } from "@/components/severity/severity-count-pills";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
  });
  // Same query key as the Projects list page, so this reuses that cache instead of
  // re-fetching — only used here for project descriptions on the Pinned Projects cards.
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
    { label: "Total Scans", value: data?.scan_count ?? 0, caption: "Across all projects" },
    { label: "Total Projects", value: data?.project_count ?? 0, caption: "All projects in your org" },
    {
      label: "Critical Findings",
      value: data?.findings_by_severity.critical ?? 0,
      caption: "Urgent action",
      pillClassName: SEVERITY_PILL_CLASS.critical,
      valueClassName: "text-severity-critical",
    },
    {
      label: "High Findings",
      value: data?.findings_by_severity.high ?? 0,
      caption: "Requires review",
      pillClassName: SEVERITY_PILL_CLASS.high,
      valueClassName: "text-severity-high",
    },
  ];

  // No "pin" concept exists yet — the most recently active distinct projects stand in
  // for it, enriched with each project's description from the projects list cache.
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
        title="Dashboard Overview"
        actions={
          <Button nativeButton={false} render={<Link href="/projects" />}>
            <Plus />
            Add project
          </Button>
        }
      />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 md:gap-6">
        {stats.map((stat) => (
          <Card key={stat.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {stat.label}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-1.5">
              {isLoading ? (
                <Skeleton className="h-9 w-12" />
              ) : (
                <span className={cn("block text-3xl font-semibold tracking-tight", stat.valueClassName)}>
                  {stat.value}
                </span>
              )}
              {stat.pillClassName ? (
                <span className={cn("inline-block rounded-full px-2 py-0.5 text-xs font-medium", stat.pillClassName)}>
                  {stat.caption}
                </span>
              ) : (
                <p className="text-xs text-muted-foreground">{stat.caption}</p>
              )}
            </CardContent>
          </Card>
        ))}
      </div>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight">Pinned Projects</h2>
          <Link href="/projects" className="text-sm font-medium text-primary hover:underline">
            Manage Pins
          </Link>
        </div>
        {isLoading ? (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {Array.from({ length: 3 }).map((_, i) => (
              <Skeleton key={i} className="h-40 w-full" />
            ))}
          </div>
        ) : pinnedProjects.length === 0 ? (
          <Card>
            <EmptyState
              icon={FolderKanban}
              title="No projects yet"
              description="Run a scan on a project to see it pinned here."
            />
          </Card>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {pinnedProjects.map(({ scan, project }) => {
              const risk = projectRiskStatus(scan.findings_by_severity);
              return (
                <Card key={scan.project_id}>
                  <CardContent className="flex h-full flex-col gap-3">
                    <div className="flex items-start justify-between gap-2">
                      <FolderKanban className="size-5 text-primary" />
                      <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", risk.className)}>
                        {risk.label}
                      </span>
                    </div>
                    <div className="flex-1">
                      <Link
                        href={`/projects/${scan.project_id}`}
                        className="font-semibold underline-offset-4 hover:underline"
                      >
                        {scan.project_name}
                      </Link>
                      <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                        {project?.description || "No description."}
                      </p>
                    </div>
                    <div className="border-t border-border pt-3">
                      <SeverityCountPills counts={scan.findings_by_severity} />
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold tracking-tight">Active Projects</h2>
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground">Filter by:</span>
            <Select value={sortBy} onValueChange={(v) => setSortBy(v as SortBy)}>
              <SelectTrigger size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="recent">Recent Activity</SelectItem>
                <SelectItem value="severity">Severity (High-Low)</SelectItem>
                <SelectItem value="status">Status</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DataTableCard
          isLoading={isLoading}
          isError={false}
          isEmpty={(data?.recent_scans.length ?? 0) === 0}
          emptyState={<EmptyState title="No scans yet" description="Run a scan to see it show up here." />}
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40">
                <TableHead>Project</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Findings</TableHead>
                <TableHead>When</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedScans.map((scan: RecentScanItem) => (
                <Fragment key={scan.scan_id}>
                  <TableRow
                    className="cursor-pointer"
                    onClick={() => toggleExpanded(scan.scan_id)}
                  >
                    <TableCell>
                      <Link
                        href={`/projects/${scan.project_id}/scans/${scan.scan_id}`}
                        className="font-medium underline-offset-4 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {scan.project_name}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <ScanTypeBadge scanType={scan.scan_type} />
                    </TableCell>
                    <TableCell>
                      <ScanStatusBadge status={scan.status} />
                    </TableCell>
                    <TableCell>
                      <SeverityCountPills counts={scan.findings_by_severity} showLabel={false} />
                    </TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {new Date(scan.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell>
                      <ChevronDown
                        className={cn(
                          "size-4 text-muted-foreground transition-transform",
                          expandedScans.has(scan.scan_id) && "rotate-180"
                        )}
                      />
                    </TableCell>
                  </TableRow>
                  {expandedScans.has(scan.scan_id) && (
                    <TableRow>
                      <TableCell colSpan={6} className="bg-muted/20 p-4">
                        <p className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                          Repositories
                        </p>
                        <ProjectRepoBreakdown projectId={scan.project_id} />
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

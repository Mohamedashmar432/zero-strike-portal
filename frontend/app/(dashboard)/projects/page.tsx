"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, FolderGit2, FolderKanban, LayoutGrid, List as ListIcon, Plus, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useMemo, useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/layout/page-header";
import { ProjectRepoBreakdown } from "@/components/projects/project-repo-breakdown";
import { SeverityCountPills } from "@/components/severity/severity-count-pills";
import { SeveritySpectrum } from "@/components/severity/severity-spectrum";
import { ScanStatusSummaryPills } from "@/components/scans/scan-status-summary-pills";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { getProjectsStats, listProjects, type ProjectStatsItem } from "@/lib/api/projects";

type StatusFilter = "all" | "active" | "archived";

const EMPTY_STATS: ProjectStatsItem = {
  project_id: "",
  total_findings: 0,
  findings_by_severity: { critical: 0, high: 0, medium: 0, low: 0, info: 0 },
  scan_status_counts: { pending: 0, queued: 0, running: 0, completed: 0, failed: 0 },
  risk_repo_count: 0,
  total_repo_count: 0,
};

function ProjectsPageContent() {
  const searchParams = useSearchParams();
  const [view, setView] = useState<"list" | "grid">("list");
  const [search, setSearch] = useState(searchParams.get("q") ?? "");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const { data, isLoading, isError } = useQuery({
    queryKey: ["projects"],
    queryFn: () => listProjects(),
  });
  const { data: stats } = useQuery({
    queryKey: ["projects", "stats"],
    queryFn: () => getProjectsStats(),
  });
  function statsFor(projectId: string): ProjectStatsItem {
    return stats?.items[projectId] ?? EMPTY_STATS;
  }

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const filtered = useMemo(() => {
    let items = data?.items ?? [];
    if (statusFilter !== "all") {
      items = items.filter((p) => (statusFilter === "archived" ? p.is_archived : !p.is_archived));
    }
    if (search) {
      const q = search.toLowerCase();
      items = items.filter((p) => p.name.toLowerCase().includes(q) || p.description?.toLowerCase().includes(q));
    }
    return items;
  }, [data, search, statusFilter]);

  const isEmpty = filtered.length === 0;
  const emptyState = (
    <EmptyState
      title={data?.items.length ? "No projects match your filters" : "No projects yet"}
      description={data?.items.length ? "Try a different search or status filter." : "Create one to start running SAST scans."}
    />
  );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Workspace / Projects"
        title="Projects"
        description="Continuous code repositories, scan histories, and vulnerabilities."
        actions={
          <>
            <div className="flex rounded-lg border border-border/80 bg-muted/30 p-0.5">
              <Button
                variant={view === "list" ? "secondary" : "ghost"}
                size="icon-xs"
                aria-label="List view"
                onClick={() => setView("list")}
                className="h-7 w-7"
              >
                <ListIcon className="size-3.5" />
              </Button>
              <Button
                variant={view === "grid" ? "secondary" : "ghost"}
                size="icon-xs"
                aria-label="Grid view"
                onClick={() => setView("grid")}
                className="h-7 w-7"
              >
                <LayoutGrid className="size-3.5" />
              </Button>
            </div>
            <Button nativeButton={false} render={<Link href="/projects/new" />} size="sm" className="gap-1.5 font-medium">
              <Plus className="size-4" />
              New Project
            </Button>
          </>
        }
      />

      <FilterBar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="Search name or description…"
        facets={[
          {
            type: "select",
            value: statusFilter,
            onChange: (v) => setStatusFilter(v as StatusFilter),
            options: [
              { value: "all", label: "All Statuses" },
              { value: "active", label: "Active" },
              { value: "archived", label: "Archived" },
            ],
          },
        ]}
      />

      {view === "grid" ? (
        <DataTableCard bare isLoading={isLoading} isError={isError} errorMessage="Failed to load projects." isEmpty={isEmpty} emptyState={emptyState}>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {filtered.map((p) => {
              const s = statsFor(p.id);
              return (
                <Card key={p.id} className="transition-colors hover:border-muted-foreground/40">
                  <CardContent className="space-y-3.5 p-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <FolderKanban className="size-4.5 shrink-0 text-muted-foreground" />
                        <Link href={`/projects/${p.id}`} className="font-semibold text-foreground text-sm truncate hover:text-primary transition-colors">
                          {p.name}
                        </Link>
                      </div>
                      {s.risk_repo_count > 0 && (
                        <span className="flex items-center gap-1 rounded-md bg-severity-critical/15 px-2 py-0.5 text-[11px] font-semibold text-severity-critical shrink-0">
                          <ShieldAlert className="size-3" />
                          {s.risk_repo_count} at risk
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground line-clamp-2">
                      {p.description || "ZeroStrike SAST project repository."}
                    </p>
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground border-t border-border/50 pt-2.5">
                      <span className="font-mono">{p.scan_count} scan{p.scan_count === 1 ? "" : "s"}</span>
                      <Badge variant={p.is_archived ? "outline" : "secondary"} className="text-[10px] uppercase font-mono">
                        {p.is_archived ? "Archived" : "Active"}
                      </Badge>
                    </div>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="readout text-sm text-foreground">
                          {s.total_findings}
                          <span className="legend ml-1.5 text-muted-foreground">findings</span>
                        </span>
                        <ScanStatusSummaryPills counts={s.scan_status_counts} />
                      </div>
                      <SeveritySpectrum counts={s.findings_by_severity} />
                      <SeverityCountPills counts={s.findings_by_severity} />
                    </div>
                    <button
                      type="button"
                      onClick={() => toggleExpanded(p.id)}
                      className="flex w-full items-center justify-between rounded-md bg-muted/30 px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
                    >
                      <span className="flex items-center gap-1.5 font-mono text-[11px]">
                        <FolderGit2 className="size-3.5 text-muted-foreground" />
                        Repositories ({s.total_repo_count})
                      </span>
                      <ChevronDown className={cn("size-3.5 transition-transform duration-150", expanded.has(p.id) && "rotate-180")} />
                    </button>
                    {expanded.has(p.id) && (
                      <div className="border-t border-border/60 pt-3">
                        <ProjectRepoBreakdown projectId={p.id} />
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            })}
          </div>
        </DataTableCard>
      ) : (
        <DataTableCard isLoading={isLoading} isError={isError} errorMessage="Failed to load projects." isEmpty={isEmpty} emptyState={emptyState}>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project Name</TableHead>
                <TableHead className="w-28">Spectrum</TableHead>
                <TableHead>Findings</TableHead>
                <TableHead>Scan Status</TableHead>
                <TableHead>At-Risk Repos</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-12">
                  <span className="sr-only">Expand row</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((p) => {
                const s = statsFor(p.id);
                return (
                  <Fragment key={p.id}>
                    <TableRow
                      className="cursor-pointer"
                      onClick={() => toggleExpanded(p.id)}
                      data-expanded={expanded.has(p.id)}
                    >
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <FolderKanban className="size-4 shrink-0 text-muted-foreground" />
                          <Link
                            href={`/projects/${p.id}`}
                            className="font-semibold text-foreground underline-offset-4 hover:underline hover:text-primary"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {p.name}
                          </Link>
                        </div>
                      </TableCell>
                      <TableCell>
                        <SeveritySpectrum counts={s.findings_by_severity} />
                      </TableCell>
                      <TableCell className="readout text-foreground">{s.total_findings}</TableCell>
                      <TableCell>
                        <ScanStatusSummaryPills counts={s.scan_status_counts} />
                      </TableCell>
                      <TableCell>
                        {s.risk_repo_count > 0 ? (
                          <span className="font-mono font-bold text-severity-critical flex items-center gap-1">
                            <ShieldAlert className="size-3.5" />
                            {s.risk_repo_count} / {s.total_repo_count}
                          </span>
                        ) : (
                          <span className="font-mono text-muted-foreground">{s.total_repo_count}</span>
                        )}
                      </TableCell>
                      <TableCell>
                        <Badge variant={p.is_archived ? "outline" : "secondary"} className="text-[10px] uppercase font-mono">
                          {p.is_archived ? "Archived" : "Active"}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <ChevronDown
                          className={cn("size-3.5 text-muted-foreground transition-transform duration-150", expanded.has(p.id) && "rotate-180")}
                        />
                      </TableCell>
                    </TableRow>
                    {expanded.has(p.id) && (
                      <TableRow className="hover:bg-transparent">
                        <TableCell colSpan={7} className="bg-muted/40 p-0">
                          <div className="p-4 pl-8 border-l-2 border-primary/50 space-y-2.5 bg-muted/20">
                            <div className="flex items-center gap-2">
                              <FolderGit2 className="size-3.5 text-muted-foreground" />
                              <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase font-mono">
                                Connected Repositories & Security Status
                              </span>
                            </div>
                            <ProjectRepoBreakdown projectId={p.id} />
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </DataTableCard>
      )}
    </div>
  );
}

export default function ProjectsPage() {
  return (
    <Suspense fallback={null}>
      <ProjectsPageContent />
    </Suspense>
  );
}

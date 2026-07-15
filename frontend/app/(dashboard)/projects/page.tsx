"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, LayoutGrid, List as ListIcon, Plus } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useMemo, useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { PageHeader } from "@/components/layout/page-header";
import { ProjectRepoBreakdown } from "@/components/projects/project-repo-breakdown";
import { ScanStatusSummaryPills } from "@/components/scans/scan-status-summary-pills";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
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
        title="Projects"
        description="Run ZeroStrike SAST scans against your codebases and review the findings."
        actions={
          <>
            <div className="flex rounded-lg border border-border p-0.5">
              <Button
                variant={view === "list" ? "secondary" : "ghost"}
                size="icon-sm"
                aria-label="List view"
                onClick={() => setView("list")}
              >
                <ListIcon />
              </Button>
              <Button
                variant={view === "grid" ? "secondary" : "ghost"}
                size="icon-sm"
                aria-label="Grid view"
                onClick={() => setView("grid")}
              >
                <LayoutGrid />
              </Button>
            </div>
            <Button nativeButton={false} render={<Link href="/projects/new" />}>
              <Plus />
              New Project
            </Button>
          </>
        }
      />

      <FilterBar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder="Search projects…"
        facets={[
          {
            type: "select",
            value: statusFilter,
            onChange: (v) => setStatusFilter(v as StatusFilter),
            options: [
              { value: "all", label: "All statuses" },
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
              <Card key={p.id}>
                <CardContent className="space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <Link href={`/projects/${p.id}`} className="font-medium underline-offset-4 hover:underline">
                      {p.name}
                    </Link>
                    {s.risk_repo_count > 0 && (
                      <span className="rounded-sm bg-severity-critical/15 px-2 py-0.5 text-xs font-medium text-severity-critical">
                        {s.risk_repo_count} at risk
                      </span>
                    )}
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {p.scan_count} scan{p.scan_count === 1 ? "" : "s"} · {p.is_archived ? "Archived" : "Active"}
                  </p>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{s.total_findings} findings</span>
                    <ScanStatusSummaryPills counts={s.scan_status_counts} />
                  </div>
                  <button
                    type="button"
                    onClick={() => toggleExpanded(p.id)}
                    className="flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
                  >
                    <ChevronDown className={cn("size-3.5 transition-transform", expanded.has(p.id) && "rotate-180")} />
                    Repositories
                  </button>
                  {expanded.has(p.id) && (
                    <div className="border-t border-border pt-3">
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
                <TableHead>Name</TableHead>
                <TableHead>Findings</TableHead>
                <TableHead>Scan Status</TableHead>
                <TableHead>At-Risk Repos</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map((p) => {
                const s = statsFor(p.id);
                return (
                <Fragment key={p.id}>
                  <TableRow className="cursor-pointer" onClick={() => toggleExpanded(p.id)}>
                    <TableCell>
                      <Link
                        href={`/projects/${p.id}`}
                        className="font-medium underline-offset-4 hover:underline"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell>{s.total_findings}</TableCell>
                    <TableCell>
                      <ScanStatusSummaryPills counts={s.scan_status_counts} />
                    </TableCell>
                    <TableCell>
                      {s.risk_repo_count > 0 ? (
                        <span className="font-mono font-semibold text-severity-critical">
                          {s.risk_repo_count} / {s.total_repo_count}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">{s.total_repo_count}</span>
                      )}
                    </TableCell>
                    <TableCell>{p.is_archived ? "Archived" : "Active"}</TableCell>
                    <TableCell>
                      <ChevronDown
                        className={cn("size-4 text-muted-foreground transition-transform", expanded.has(p.id) && "rotate-180")}
                      />
                    </TableCell>
                  </TableRow>
                  {expanded.has(p.id) && (
                    <TableRow>
                      <TableCell colSpan={6} className="bg-muted/20 p-4">
                        <p className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                          Repositories
                        </p>
                        <ProjectRepoBreakdown projectId={p.id} />
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

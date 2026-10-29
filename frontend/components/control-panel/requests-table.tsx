"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ExternalLink } from "lucide-react";
import Link from "next/link";
import { Fragment, useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listScanRequests, type InsightsRange } from "@/lib/api/project-insights";
import { queryKeys } from "@/lib/api/query-keys";
import { SCAN_STAGE_LABELS, type ScanType } from "@/lib/api/scans";
import { fmt, when } from "./date-range";

const ALL = "all"; // sentinel for "no filter"; FilterBar maps it to its label.
const PAGE_SIZE = 25;

/**
 * Scan requests with their errors. With `fixedProjectId` the project filter is hidden and pinned
 * (the Project activity tab); otherwise `projects` feeds the project filter.
 */
export function RequestsTable({
  range,
  fixedProjectId,
  projects = [],
}: {
  range: InsightsRange | null;
  fixedProjectId?: string;
  projects?: { project_id: string; name: string }[];
}) {
  const [failedOnly, setFailedOnly] = useState(ALL);
  const [scanType, setScanType] = useState(ALL);
  const [projectId, setProjectId] = useState(ALL);
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const filters = {
    since: range?.since ?? "",
    until: range?.until ?? "",
    projectId: fixedProjectId ?? (projectId === ALL ? undefined : projectId),
    scanType: scanType === ALL ? undefined : (scanType as ScanType),
    status: failedOnly === "failed" ? ("failed" as const) : undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  };
  const requests = useQuery({
    queryKey: queryKeys.admin.scanRequests(filters),
    queryFn: () => listScanRequests(filters),
    enabled: range !== null,
    placeholderData: keepPreviousData,
  });

  const totalPages = Math.max(1, Math.ceil((requests.data?.total ?? 0) / PAGE_SIZE));
  const resetPage = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setPage(1);
  };
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="space-y-3">
      <FilterBar
        facets={[
          {
            type: "select",
            value: failedOnly,
            onChange: resetPage(setFailedOnly),
            placeholder: "Status",
            options: [
              { value: ALL, label: "All requests" },
              { value: "failed", label: "Failed only" },
            ],
          },
          {
            type: "select",
            value: scanType,
            onChange: resetPage(setScanType),
            placeholder: "Scan type",
            options: [
              { value: ALL, label: "Cloud and CI/CD" },
              { value: "cloud", label: "Cloud" },
              { value: "cicd", label: "CI/CD" },
            ],
          },
          ...(fixedProjectId
            ? []
            : [
                {
                  type: "select" as const,
                  value: projectId,
                  onChange: resetPage(setProjectId),
                  placeholder: "Project",
                  options: [
                    { value: ALL, label: "All projects" },
                    ...projects.map((p) => ({ value: p.project_id, label: p.name })),
                  ],
                },
              ]),
        ]}
      />
      <DataTableCard
        isLoading={requests.isLoading}
        isError={requests.isError}
        errorMessage="Failed to load scan requests."
        isEmpty={(requests.data?.items.length ?? 0) === 0}
        emptyState={
          <EmptyState title="No scan requests" description="Nothing matches these filters in the selected window." />
        }
      >
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 text-xs">
              <TableHead className="w-8 py-2.5" />
              <TableHead className="py-2.5">Requested</TableHead>
              <TableHead className="py-2.5">Project</TableHead>
              <TableHead className="py-2.5">Type</TableHead>
              <TableHead className="py-2.5">Status</TableHead>
              <TableHead className="py-2.5">Triggered by</TableHead>
              <TableHead className="py-2.5">Branch</TableHead>
              <TableHead className="py-2.5" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {requests.data?.items.map((r) => {
              const open = expanded.has(r.scan_id);
              return (
                <Fragment key={r.scan_id}>
                  <TableRow className="align-top text-xs">
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="icon-xs"
                        aria-label={open ? "Hide details" : "Show details"}
                        aria-expanded={open}
                        onClick={() => toggle(r.scan_id)}
                      >
                        {open ? <ChevronDown /> : <ChevronRight />}
                      </Button>
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-muted-foreground">
                      {when(r.created_at)}
                    </TableCell>
                    <TableCell className="font-medium text-foreground">
                      {r.project_name ? (
                        <Link href={`/projects/${r.project_id}`} className="hover:underline">
                          {r.project_name}
                        </Link>
                      ) : (
                        // A link to a deleted project could only 404.
                        <span className="text-muted-foreground">Deleted project</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <ScanTypeBadge scanType={r.scan_type} />
                    </TableCell>
                    <TableCell>
                      <ScanStatusBadge status={r.status} scanId={r.scan_id} />
                      {r.quota_exempt && (
                        <span className="legend ml-1.5 text-muted-foreground" title="Not counted against the quota">
                          exempt
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="max-w-48 truncate text-muted-foreground" title={r.triggered_by ?? undefined}>
                      {r.triggered_by ?? "—"}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground">{r.branch ?? "—"}</TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1">
                        {r.project_name && (
                          <Button
                            size="xs"
                            variant="outline"
                            nativeButton={false}
                            render={<Link href={`/projects/${r.project_id}/scans/${r.scan_id}`} />}
                          >
                            View
                          </Button>
                        )}
                        {r.ci_build_url && (
                          <Button
                            size="xs"
                            variant="ghost"
                            nativeButton={false}
                            render={<a href={r.ci_build_url} target="_blank" rel="noopener noreferrer" />}
                          >
                            CI build <ExternalLink />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                  {open && (
                    <TableRow className="bg-muted/20 text-xs hover:bg-muted/20">
                      <TableCell />
                      <TableCell colSpan={7} className="space-y-1.5 whitespace-normal break-words">
                        {r.error_message ? (
                          <p className="whitespace-pre-wrap font-mono text-severity-critical">{r.error_message}</p>
                        ) : (
                          <p className="text-muted-foreground">
                            {r.status === "failed" ? "No error message was recorded." : "No error recorded."}
                          </p>
                        )}
                        <dl className="flex flex-wrap gap-x-5 gap-y-1 text-muted-foreground">
                          {r.stage && (
                            <div>
                              <dt className="legend inline">Stage </dt>
                              <dd className="inline font-mono">{SCAN_STAGE_LABELS[r.stage]}</dd>
                            </div>
                          )}
                          {r.repo_url && (
                            <div>
                              <dt className="legend inline">Repo </dt>
                              <dd className="inline font-mono">{r.repo_url}</dd>
                            </div>
                          )}
                          {r.scan_label && (
                            <div>
                              <dt className="legend inline">Label </dt>
                              <dd className="inline font-mono">{r.scan_label}</dd>
                            </div>
                          )}
                          {r.ci_provider && (
                            <div>
                              <dt className="legend inline">CI </dt>
                              <dd className="inline font-mono">{r.ci_provider}</dd>
                            </div>
                          )}
                          <div>
                            <dt className="legend inline">Started </dt>
                            <dd className="inline font-mono">{when(r.started_at)}</dd>
                          </div>
                          <div>
                            <dt className="legend inline">Completed </dt>
                            <dd className="inline font-mono">{when(r.completed_at)}</dd>
                          </div>
                        </dl>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      </DataTableCard>

      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {fmt(requests.data?.total ?? 0)} request{requests.data?.total === 1 ? "" : "s"} in this window
        </p>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Previous
          </Button>
          <span className="font-mono text-xs text-muted-foreground">
            {page} / {totalPages}
          </span>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}

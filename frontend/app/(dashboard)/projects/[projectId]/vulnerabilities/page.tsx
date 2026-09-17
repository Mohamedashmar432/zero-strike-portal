"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { listMembers } from "@/lib/api/project-members";
import { listProjectRepos } from "@/lib/api/project-repos";
import { getProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import { listScans } from "@/lib/api/scans";
import type { Severity } from "@/lib/api/findings";
import {
  listVulnerabilities,
  type RegressionState,
  type Vulnerability,
  type VulnerabilityStatus,
} from "@/lib/api/vulnerabilities";
import { PRIORITY_CLASS } from "@/lib/priority";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { RelativeTime } from "@/components/common/relative-time";
import { RegressionBadge } from "@/components/vulnerabilities/regression-badge";
import { VulnerabilityStatusBadge } from "@/components/vulnerabilities/vulnerability-status-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const STATUSES: VulnerabilityStatus[] = ["open", "in_progress", "resolved", "accepted_risk"];
const REGRESSION_STATES: RegressionState[] = ["new", "reopened", "fixed", "unchanged"];
const ALL = "__all__";
const PAGE_SIZE = 25;

const STATUS_LABELS: Record<VulnerabilityStatus, string> = {
  open: "Open",
  in_progress: "In Progress",
  resolved: "Resolved",
  accepted_risk: "Accepted Risk",
};
const REGRESSION_LABELS: Record<RegressionState, string> = {
  new: "New",
  reopened: "Reopened",
  fixed: "Fixed",
  unchanged: "Unchanged",
};

function fileLine(file: string, line: number | null) {
  return line ? `${file}:${line}` : file;
}

export default function VulnerabilitiesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();

  const status = (searchParams.get("status") as VulnerabilityStatus | null) ?? undefined;
  const severity = (searchParams.get("severity") as Severity | null) ?? undefined;
  const regressionState = (searchParams.get("regression") as RegressionState | null) ?? undefined;
  const assigneeUserId = searchParams.get("assignee") ?? undefined;
  const search = searchParams.get("q") ?? "";
  const page = Math.max(1, Number(searchParams.get("page") ?? "1") || 1);

  // URL-synced filters -- router.replace (not push) + scroll:false, same convention as the
  // project detail page's tab switching, so a shared link reproduces the exact view and the
  // back button doesn't pile up one history entry per keystroke.
  function updateParams(patch: Record<string, string | undefined>, resetPage = true) {
    const params = new URLSearchParams(searchParams.toString());
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined || value === "") params.delete(key);
      else params.set(key, value);
    }
    if (resetPage) params.delete("page");
    const query = params.toString();
    router.replace(`/projects/${projectId}/vulnerabilities${query ? `?${query}` : ""}`, { scroll: false });
  }

  const { data: project } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });

  // Shared cache key/args with the project's Scans tab -- whether any scan has ever run is
  // what tells "no scans yet" apart from "scans ran, nothing came out of them".
  const { data: scans } = useQuery({
    queryKey: queryKeys.projects.scans(projectId),
    queryFn: () => listScans(projectId),
  });

  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });
  const repoById = new Map((repos ?? []).map((r) => [r.id, r]));

  const { data: members } = useQuery({
    queryKey: queryKeys.projects.members(projectId),
    queryFn: () => listMembers(projectId),
  });
  // Only members with a linked user_id can ever be an assignee (see
  // update_vulnerability_assignment) -- a still-pending invite can't be selected.
  const assignableMembers = (members ?? []).filter((m) => m.user_id);

  const filters = { status, severity, regressionState, assigneeUserId, search, page };
  const {
    data: vulnerabilities,
    isLoading,
    isError,
  } = useQuery({
    queryKey: queryKeys.projects.vulnerabilities(projectId, filters),
    queryFn: () =>
      listVulnerabilities(projectId, {
        status,
        severity,
        regressionState,
        assigneeUserId,
        search: search || undefined,
        page,
        pageSize: PAGE_SIZE,
      }),
    placeholderData: keepPreviousData,
  });

  const totalPages = vulnerabilities ? Math.max(1, Math.ceil(vulnerabilities.total / PAGE_SIZE)) : 1;
  const hasFilters = !!(status || severity || regressionState || assigneeUserId || search);
  const noScansYet = (scans?.total ?? null) === 0;
  const isEmpty = !!vulnerabilities && vulnerabilities.items.length === 0;

  function repoLabel(v: Vulnerability) {
    if (!v.project_repo_id) return "Unlinked";
    const repo = repoById.get(v.project_repo_id);
    return repo ? repo.label || repo.repo_full_name : "Unlinked";
  }

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[
          { label: "Projects", href: "/projects" },
          { label: project?.name ?? projectId, href: `/projects/${projectId}` },
          { label: "Vulnerabilities" },
        ]}
      />

      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">Vulnerabilities</h1>
        <p className="text-sm text-muted-foreground">
          The canonical, cross-scan work queue -- every fingerprint that has ever recurred here,
          triaged once rather than re-triaged on every rescan.
        </p>
      </div>

      <FilterBar
        search={search}
        onSearchChange={(v) => updateParams({ q: v })}
        searchPlaceholder="Search rule, message, or fingerprint…"
        facets={[
          {
            type: "select",
            value: status ?? ALL,
            onChange: (v) => updateParams({ status: v === ALL ? undefined : v }),
            placeholder: "Status",
            options: [
              { value: ALL, label: "All statuses" },
              ...STATUSES.map((s) => ({ value: s, label: STATUS_LABELS[s] })),
            ],
          },
          {
            type: "select",
            value: severity ?? ALL,
            onChange: (v) => updateParams({ severity: v === ALL ? undefined : v }),
            placeholder: "Severity",
            options: [
              { value: ALL, label: "All severities" },
              ...SEVERITIES.map((s) => ({ value: s, label: s })),
            ],
          },
          {
            type: "select",
            value: regressionState ?? ALL,
            onChange: (v) => updateParams({ regression: v === ALL ? undefined : v }),
            placeholder: "Regression",
            options: [
              { value: ALL, label: "All regression states" },
              ...REGRESSION_STATES.map((s) => ({ value: s, label: REGRESSION_LABELS[s] })),
            ],
          },
          {
            type: "select",
            value: assigneeUserId ?? ALL,
            onChange: (v) => updateParams({ assignee: v === ALL ? undefined : v }),
            placeholder: "Owner",
            options: [
              { value: ALL, label: "All owners" },
              ...assignableMembers.map((m) => ({
                value: m.user_id as string,
                label: m.name ?? m.invited_email,
              })),
            ],
          },
        ]}
      />

      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load vulnerabilities."
        isEmpty={isEmpty}
        emptyState={
          noScansYet ? (
            <EmptyState
              title="No scans yet"
              description="Run a scan first -- vulnerabilities are built from scan findings, so there's nothing to triage until one completes."
            />
          ) : hasFilters ? (
            <EmptyState title="No vulnerabilities match these filters" description="Try clearing a filter or search term." />
          ) : (
            <EmptyState
              title="No vulnerabilities"
              description="Nothing has recurred across scans yet -- vulnerabilities appear here once a finding's fingerprint is confirmed by reconciliation."
            />
          )
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Vulnerability</TableHead>
              <TableHead>Repository</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Regression</TableHead>
              <TableHead>Owner</TableHead>
              <TableHead>First seen</TableHead>
              <TableHead>Last seen</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {vulnerabilities?.items.map((v) => (
              <TableRow key={v.id}>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    {v.current_severity && <SeverityBadge severity={v.current_severity} />}
                    {v.current_priority_tier && (
                      <span className={`font-mono text-[10px] font-semibold ${PRIORITY_CLASS[v.current_priority_tier]}`}>
                        {v.current_priority_score != null ? v.current_priority_score.toFixed(1) : ""}
                      </span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="max-w-64">
                  <p className="truncate text-xs font-semibold text-foreground">
                    {v.current_rule_name || v.current_rule_id || "Vulnerability"}
                  </p>
                  {v.current_message && (
                    <p className="truncate text-xs text-muted-foreground">{v.current_message}</p>
                  )}
                  <p className="font-mono text-[10px] text-muted-foreground/70">{v.fingerprint.slice(0, 12)}</p>
                </TableCell>
                <TableCell className="max-w-40 truncate font-mono text-xs" title={repoLabel(v)}>
                  {repoLabel(v)}
                </TableCell>
                <TableCell className="max-w-48 truncate font-mono text-xs">
                  {v.current_location ? fileLine(v.current_location.file, v.current_location.start_line) : "—"}
                </TableCell>
                <TableCell>
                  <VulnerabilityStatusBadge status={v.status} />
                </TableCell>
                <TableCell>
                  <RegressionBadge state={v.last_regression_state} />
                </TableCell>
                <TableCell className="text-xs">{v.assignee_email ?? "Unassigned"}</TableCell>
                <TableCell className="text-xs">
                  <RelativeTime iso={v.first_seen_at} />
                </TableCell>
                <TableCell className="text-xs">
                  <RelativeTime iso={v.last_seen_at} />
                </TableCell>
                <TableCell>
                  <Button
                    variant="outline"
                    size="sm"
                    nativeButton={false}
                    render={<Link href={`/projects/${projectId}/vulnerabilities/${v.id}`} />}
                  >
                    View
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>

      {vulnerabilities && vulnerabilities.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">
            Page {page} of {totalPages} · {vulnerabilities.total} vulnerabilities
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => updateParams({ page: String(page - 1) }, false)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => updateParams({ page: String(page + 1) }, false)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

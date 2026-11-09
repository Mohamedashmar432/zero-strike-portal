"use client";

import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { MetricStrip } from "@/components/common/metric-strip";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { BulkActionBar, type BulkOutcome } from "@/components/vulnerabilities/bulk-action-bar";
import { FacetPanel } from "@/components/vulnerabilities/facet-panel";
import { FilterChips } from "@/components/vulnerabilities/filter-chips";
import { ResultCount } from "@/components/vulnerabilities/result-count";
import { RiskAcceptedPanel } from "@/components/vulnerabilities/risk-accepted-panel";
import { SavedViews } from "@/components/vulnerabilities/saved-views";
import { VulnerabilityTable } from "@/components/vulnerabilities/vulnerability-table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { listMembers } from "@/lib/api/project-members";
import { listProjectRepos } from "@/lib/api/project-repos";
import { getProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import { listRiskAcceptances } from "@/lib/api/risk-acknowledgements";
import { listScans } from "@/lib/api/scans";
import {
  getVulnerabilityFacets,
  getVulnerabilitySummary,
  listVulnerabilities,
  UNLINKED_REPO_KEY,
} from "@/lib/api/vulnerabilities";
import { useHasRole } from "@/lib/hooks/use-has-role";
import {
  EMPTY_FILTERS,
  UNASSIGNED,
  activeFilterCount,
  chipsOf,
  nextSort,
  parseFilters,
  parsePage,
  parseSort,
  parseView,
  removeChip,
  toApiParams,
  toUrlQuery,
  toggleValue,
  type Chip,
  type FilterState,
  type MultiKey,
  type SortColumn,
  type View,
} from "@/lib/vulnerability-filters";

const PAGE_SIZE = 25;

export default function VulnerabilitiesPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const isAdmin = useHasRole("admin");

  // Everything the page shows is derived from the URL, so a shared link reproduces the exact view.
  const view: View = parseView(searchParams);
  const filters: FilterState = useMemo(() => parseFilters(searchParams), [searchParams]);
  const sort = parseSort(searchParams);
  const page = parsePage(searchParams);

  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());

  // router.replace (not push) + scroll:false, as before: the back button must not pile up one history
  // entry per click, and the page must not jump to the top.
  function navigate(next: { filters?: FilterState; sort?: string; page?: number; view?: View }) {
    const q = toUrlQuery({
      filters: next.filters ?? filters,
      sort: next.sort ?? sort,
      page: next.page ?? 1,
      view: next.view ?? view,
    });
    setSelected(new Set());
    router.replace(`/projects/${projectId}/vulnerabilities${q ? `?${q}` : ""}`, { scroll: false });
  }

  // Search box: local text, written to the URL after a pause (and re-synced when the URL changes).
  const [searchText, setSearchText] = useState(filters.search);
  const [syncedSearch, setSyncedSearch] = useState(filters.search);
  if (filters.search !== syncedSearch) {
    setSyncedSearch(filters.search);
    setSearchText(filters.search);
  }
  useEffect(() => {
    if (searchText === filters.search) return;
    const t = setTimeout(() => navigate({ filters: { ...filters, search: searchText.trim() } }), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchText]);

  const { data: project } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });
  const { data: scans } = useQuery({
    queryKey: queryKeys.projects.scans(projectId),
    queryFn: () => listScans(projectId),
  });
  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });
  const { data: members } = useQuery({
    queryKey: queryKeys.projects.members(projectId),
    queryFn: () => listMembers(projectId),
  });
  const assignable = (members ?? [])
    .filter((m) => m.user_id)
    .map((m) => ({ user_id: m.user_id as string, label: m.name ?? m.invited_email }));

  const apiParams = useMemo(() => toApiParams(filters), [filters]);
  const apiKey = apiParams.toString();

  const {
    data: vulns,
    isLoading,
    isError,
  } = useQuery({
    queryKey: queryKeys.projects.vulnerabilities(projectId, { q: apiKey, sort, page }),
    queryFn: () => listVulnerabilities(projectId, apiParams, { page, pageSize: PAGE_SIZE, sort }),
    placeholderData: keepPreviousData,
    enabled: view === "all",
  });
  const { data: facets, isLoading: facetsLoading } = useQuery({
    queryKey: queryKeys.projects.vulnerabilityFacets(projectId, apiKey),
    queryFn: () => getVulnerabilityFacets(projectId, apiParams),
    placeholderData: keepPreviousData,
    enabled: view === "all",
  });
  const { data: summary } = useQuery({
    queryKey: queryKeys.projects.vulnerabilitySummary(projectId),
    queryFn: () => getVulnerabilitySummary(projectId),
    enabled: view === "all",
  });
  // Tab badge only; the panel loads its own pages.
  const { data: riskCount } = useQuery({
    queryKey: queryKeys.projects.riskAcceptances(projectId, "accepted-count", 1),
    queryFn: () => listRiskAcceptances(projectId, { reviewStatus: "accepted", page: 1, pageSize: 1 }),
  });

  const repoById = new Map((repos ?? []).map((r) => [r.id, r]));
  const repoName = (key: string) => {
    if (key === UNLINKED_REPO_KEY) return "Unlinked";
    const r = repoById.get(key);
    return r ? r.label || r.repo_full_name : "Unlinked";
  };

  function chipLabel(chip: Chip): string {
    if (chip.key === "repo") return repoName(chip.value);
    if (chip.key === "assignee") {
      if (chip.value === UNASSIGNED) return "Unassigned";
      return (
        assignable.find((m) => m.user_id === chip.value)?.label ??
        facets?.assignee.find((a) => a.id === chip.value)?.email ??
        "Unknown user"
      );
    }
    if (chip.key === "rule") return facets?.rule.find((r) => r.id === chip.value)?.name || chip.value;
    return chip.value.replace(/_/g, " ");
  }

  const items = vulns?.items ?? [];
  const nameOf = (id: string) => {
    const v = items.find((x) => x.id === id);
    return v?.current_rule_name || v?.current_rule_id || id;
  };
  const totalPages = vulns ? Math.max(1, Math.ceil(vulns.total / PAGE_SIZE)) : 1;
  const count = activeFilterCount(filters);
  const noScansYet = (scans?.total ?? null) === 0;
  const isEmpty = !!vulns && items.length === 0;

  function onOutcome(outcome: BulkOutcome) {
    queryClient.invalidateQueries({ queryKey: ["projects", projectId, "vulnerabilities"] });
    queryClient.invalidateQueries({ queryKey: ["projects", projectId, "risk-acceptances"] });
    setSelected(new Set(outcome.failed.map((f) => f.id)));
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
          The canonical, cross-scan work queue: every fingerprint that has ever recurred here, triaged once rather
          than re-triaged on every rescan.
        </p>
      </div>

      <Tabs value={view} onValueChange={(v) => navigate({ view: v as View })}>
        <TabsList variant="line">
          <TabsTrigger value="all">All findings</TabsTrigger>
          <TabsTrigger value="risk">Risk accepted{riskCount ? ` (${riskCount.accepted_count})` : ""}</TabsTrigger>
        </TabsList>
      </Tabs>

      {view === "risk" ? (
        <RiskAcceptedPanel projectId={projectId} isAdmin={isAdmin} isOwner={project?.my_role === "owner"} />
      ) : (
        <>
          {/* The overall picture leads: it is the context for the filters and the table below. */}
          <section aria-label="Project totals" className="space-y-2">
            <p className="legend text-muted-foreground">Project totals, unfiltered</p>
            <MetricStrip
              isLoading={!summary}
              metrics={[
                { label: "Open", value: (summary?.open ?? 0).toLocaleString(), tone: (summary?.open ?? 0) > 0 ? "critical" : "default" },
                { label: "In progress", value: (summary?.in_progress ?? 0).toLocaleString() },
                { label: "Reopened", value: (summary?.reopened ?? 0).toLocaleString(), tone: (summary?.reopened ?? 0) > 0 ? "high" : "default" },
                { label: "Fixed", value: (summary?.fixed ?? 0).toLocaleString(), tone: "signal" },
              ]}
            />
          </section>

          {/* Sticky: the search, the active filters and the result count stay in view while the table scrolls. */}
          <div className="sticky top-0 z-30 -mx-2 space-y-2 border-b border-hairline bg-background/95 px-2 py-3 backdrop-blur">
            <div className="flex flex-wrap items-center gap-3">
              <div className="relative w-full max-w-sm">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <Input
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  aria-label="Search rule, message or fingerprint"
                  placeholder="Search rule, message or fingerprint…"
                  className="pl-8"
                />
              </div>
              <ResultCount total={vulns?.total} isLoading={isLoading && !vulns} filterCount={count} />
              <div className="ml-auto">
                <SavedViews
                  projectId={projectId}
                  currentQuery={toUrlQuery({ filters, sort })}
                  onApply={(q) => router.replace(`/projects/${projectId}/vulnerabilities${q ? `?${q}` : ""}`, { scroll: false })}
                />
              </div>
            </div>
            <FilterChips
              chips={chipsOf(filters)}
              labelFor={chipLabel}
              onRemove={(chip) => navigate({ filters: removeChip(filters, chip) })}
              onClear={() => navigate({ filters: EMPTY_FILTERS })}
            />
          </div>

          <div className="grid items-start gap-6 lg:grid-cols-[15rem_minmax(0,1fr)]">
            <FacetPanel
              facets={facets}
              isLoading={facetsLoading}
              filters={filters}
              repoLabel={repoName}
              onToggle={(key: MultiKey, value) => navigate({ filters: toggleValue(filters, key, value) })}
              onSetSingle={(key, value) => navigate({ filters: { ...filters, [key]: value } })}
              onPathChange={(path) => navigate({ filters: { ...filters, path: path.trim() } })}
            />

            <div className="min-w-0 space-y-4">
              <DataTableCard
                isLoading={isLoading}
                isError={isError}
                errorMessage="Failed to load vulnerabilities."
                isEmpty={isEmpty}
                emptyState={
                  noScansYet ? (
                    <EmptyState
                      title="No scans yet"
                      description="Run a scan first. Vulnerabilities are built from scan findings, so there is nothing to triage until one completes."
                    />
                  ) : count > 0 ? (
                    <EmptyState
                      title="No vulnerabilities match these filters"
                      description="Remove a filter or clear the search."
                      action={
                        <Button size="sm" variant="outline" onClick={() => navigate({ filters: EMPTY_FILTERS })}>
                          Clear all filters
                        </Button>
                      }
                    />
                  ) : (
                    <EmptyState
                      title="No vulnerabilities"
                      description="Nothing has recurred across scans yet. Vulnerabilities appear here once a finding's fingerprint is confirmed by reconciliation."
                    />
                  )
                }
              >
                <VulnerabilityTable
                  projectId={projectId}
                  items={items}
                  sort={sort}
                  onSort={(c: SortColumn) => navigate({ sort: nextSort(sort, c) })}
                  selected={selected}
                  canSelect
                  onToggleRow={(id) =>
                    setSelected((prev) => {
                      const n = new Set(prev);
                      if (!n.delete(id)) n.add(id);
                      return n;
                    })
                  }
                  onToggleAll={() =>
                    setSelected((prev) => {
                      const every = items.every((v) => prev.has(v.id));
                      const n = new Set(prev);
                      for (const v of items) {
                        if (every) n.delete(v.id);
                        else n.add(v.id);
                      }
                      return n;
                    })
                  }
                />
              </DataTableCard>

              {vulns && vulns.total > 0 && (
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-muted-foreground">
                    Page {page} of {totalPages}
                  </span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => navigate({ page: page - 1 })}>
                      Previous
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={page >= totalPages}
                      onClick={() => navigate({ page: page + 1 })}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}

              <BulkActionBar
                projectId={projectId}
                selectedIds={[...selected]}
                members={assignable}
                nameOf={nameOf}
                onClear={() => setSelected(new Set())}
                onOutcome={onOutcome}
              />
            </div>
          </div>

        </>
      )}
    </div>
  );
}

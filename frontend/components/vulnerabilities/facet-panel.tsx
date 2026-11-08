"use client";

import { useState } from "react";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { VulnerabilityFacets } from "@/lib/api/vulnerabilities";
import { cn } from "@/lib/utils";
import { UNASSIGNED, type FilterState, type MultiKey } from "@/lib/vulnerability-filters";

type Option = { value: string; label: string; count: number | null };

const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"];
const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  accepted_risk: "Accepted risk",
  false_positive: "False positive",
};
const KIND_LABELS: Record<string, string> = {
  sast: "Code (SAST)",
  secret: "Secret",
  sca: "Dependency (SCA)",
  config: "Config",
  ioc: "Indicator of compromise",
};
const REVIEW_LABELS: Record<string, string> = {
  none: "No review",
  pending: "Pending",
  accepted: "Accepted",
  rejected: "Rejected",
  revoked: "Revoked",
};
const REVIEW_KIND_LABELS: Record<string, string> = { false_positive: "False positive", accepted_risk: "Accepted risk" };
const FIX_LABELS: Record<string, string> = { open: "Open", reopened: "Reopened", fixed: "Fixed", dismissed: "Dismissed" };
const AGE_LABELS: Record<string, string> = {
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  "90d": "Last 90 days",
  "90d+": "Older than 90 days",
};
const REGRESSION_LABELS: Record<string, string> = { new: "New", reopened: "Reopened", fixed: "Fixed", unchanged: "Unchanged" };

/** Facet values with a count, plus any selected value the server no longer reports (count 0). */
function build(
  counts: Record<string, number> | undefined,
  selected: string[],
  labels: (v: string) => string,
  order?: string[]
): Option[] {
  const keys = new Set([...Object.keys(counts ?? {}), ...selected]);
  const list = [...keys].map((v) => ({ value: v, label: labels(v), count: counts?.[v] ?? 0 }));
  if (order) list.sort((a, b) => order.indexOf(a.value) - order.indexOf(b.value));
  else list.sort((a, b) => (b.count ?? 0) - (a.count ?? 0) || a.label.localeCompare(b.label));
  return list;
}

function Group({
  title,
  options,
  selected,
  onToggle,
  single = false,
}: {
  title: string;
  options: Option[];
  selected: string[];
  onToggle: (value: string) => void;
  single?: boolean;
}) {
  if (options.length === 0) return null;
  return (
    <fieldset className="space-y-1 border-0 p-0">
      <legend className="legend mb-1 text-muted-foreground">{title}</legend>
      {options.map((o) => {
        const checked = selected.includes(o.value);
        return (
          <label
            key={o.value}
            className={cn(
              "flex cursor-pointer items-center gap-2 rounded-sm px-1.5 py-1 text-xs transition-colors hover:bg-muted/60",
              checked && "bg-muted/50 font-medium text-foreground"
            )}
          >
            <input
              type={single ? "radio" : "checkbox"}
              name={single ? `facet-${title}` : undefined}
              className="size-3.5 shrink-0 accent-[var(--primary)]"
              checked={checked}
              // A radio cannot be un-ticked by clicking it again; the click handler does that.
              onChange={() => onToggle(o.value)}
              onClick={() => single && checked && onToggle(o.value)}
            />
            <span className="min-w-0 flex-1 truncate" title={o.label}>
              {o.label}
            </span>
            {o.count !== null && (
              <span className="font-mono text-[11px] tabular-nums text-muted-foreground">{o.count.toLocaleString()}</span>
            )}
          </label>
        );
      })}
    </fieldset>
  );
}

export function FacetPanel({
  facets,
  isLoading,
  filters,
  onToggle,
  onSetSingle,
  onPathChange,
  repoLabel,
}: {
  facets: VulnerabilityFacets | undefined;
  isLoading: boolean;
  filters: FilterState;
  onToggle: (key: MultiKey, value: string) => void;
  onSetSingle: (key: "fix_status" | "regression", value: string) => void;
  onPathChange: (path: string) => void;
  repoLabel: (key: string) => string;
}) {
  const [path, setPath] = useState(filters.path);
  const [syncedPath, setSyncedPath] = useState(filters.path);
  // Adjust-state-during-render: follow the URL when it changes underneath us (saved view, back button).
  if (filters.path !== syncedPath) {
    setSyncedPath(filters.path);
    setPath(filters.path);
  }

  if (isLoading && !facets) {
    return (
      <div className="space-y-3" aria-hidden="true">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-16 w-full" />
        ))}
      </div>
    );
  }

  const assigneeLabel = (id: string) =>
    id === UNASSIGNED ? "Unassigned" : (facets?.assignee.find((a) => a.id === id)?.email ?? "Unknown user");
  const ruleLabel = (id: string) => facets?.rule.find((r) => r.id === id)?.name || id;

  const assignee: Option[] = build(
    Object.fromEntries((facets?.assignee ?? []).map((a) => [a.id, a.count])),
    filters.assignee,
    assigneeLabel
  );
  const rule: Option[] = build(
    Object.fromEntries((facets?.rule ?? []).map((r) => [r.id, r.count])),
    filters.rule,
    ruleLabel
  );

  return (
    <aside aria-label="Filter findings" className="space-y-4">
      <Group
        title="Severity"
        options={build(facets?.severity, filters.severity, (v) => v, SEVERITY_ORDER)}
        selected={filters.severity}
        onToggle={(v) => onToggle("severity", v)}
      />
      <Group
        title="Status"
        options={build(facets?.status, filters.status, (v) => STATUS_LABELS[v] ?? v)}
        selected={filters.status}
        onToggle={(v) => onToggle("status", v)}
      />
      <Group
        title="Kind"
        options={build(facets?.kind, filters.kind, (v) => KIND_LABELS[v] ?? v)}
        selected={filters.kind}
        onToggle={(v) => onToggle("kind", v)}
      />
      <Group
        title="Review"
        options={build(facets?.review_state, filters.review_state, (v) => REVIEW_LABELS[v] ?? v)}
        selected={filters.review_state}
        onToggle={(v) => onToggle("review_state", v)}
      />
      <Group
        title="Review kind"
        options={build(facets?.review_kind, filters.review_kind, (v) => REVIEW_KIND_LABELS[v] ?? v)}
        selected={filters.review_kind}
        onToggle={(v) => onToggle("review_kind", v)}
      />
      <Group
        title="Fix status"
        single
        options={build(facets?.fix_status, filters.fix_status ? [filters.fix_status] : [], (v) => FIX_LABELS[v] ?? v)}
        selected={filters.fix_status ? [filters.fix_status] : []}
        onToggle={(v) => onSetSingle("fix_status", filters.fix_status === v ? "" : v)}
      />
      <Group
        title="Regression"
        single
        options={Object.keys(REGRESSION_LABELS).map((v) => ({ value: v, label: REGRESSION_LABELS[v], count: null }))}
        selected={filters.regression ? [filters.regression] : []}
        onToggle={(v) => onSetSingle("regression", filters.regression === v ? "" : v)}
      />
      <Group
        title="First seen"
        options={build(facets?.age, filters.age, (v) => AGE_LABELS[v] ?? v, ["7d", "30d", "90d", "90d+"])}
        selected={filters.age}
        onToggle={(v) => onToggle("age", v)}
      />
      <Group
        title="Repository"
        options={build(facets?.repo, filters.repo, repoLabel)}
        selected={filters.repo}
        onToggle={(v) => onToggle("repo", v)}
      />
      <Group title="Assignee" options={assignee} selected={filters.assignee} onToggle={(v) => onToggle("assignee", v)} />
      <Group title="Rule" options={rule} selected={filters.rule} onToggle={(v) => onToggle("rule", v)} />

      <div className="space-y-1">
        <label htmlFor="facet-path" className="legend text-muted-foreground">
          File path contains
        </label>
        <Input
          id="facet-path"
          value={path}
          placeholder="src/api/"
          className="h-8 text-xs"
          onChange={(e) => setPath(e.target.value)}
          onBlur={() => path !== filters.path && onPathChange(path)}
          onKeyDown={(e) => e.key === "Enter" && onPathChange(path)}
        />
      </div>
    </aside>
  );
}

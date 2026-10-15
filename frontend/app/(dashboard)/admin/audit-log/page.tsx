"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, ScrollText, ServerCrash } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { MetricStrip } from "@/components/common/metric-strip";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  auditDetail,
  formatAuditAction,
  listAuditLogs,
  listSystemLogs,
  type AuditCategory,
  type AuditFilter,
  type DateRange,
  type SystemLogLevel,
} from "@/lib/api/audit-logs";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

const CATEGORY_TAG: Record<AuditCategory, string> = {
  privilege: "border-severity-high bg-severity-high-tint text-severity-high",
  project: "border-signal bg-signal/10 text-signal",
  admin: "border-muted-foreground/40 bg-muted text-muted-foreground",
};

const CATEGORY_LABEL: Record<AuditCategory, string> = {
  privilege: "privilege",
  project: "project",
  admin: "admin",
};

const LEVEL_TAG: Record<SystemLogLevel, string> = {
  critical: "border-severity-critical bg-severity-critical-tint text-severity-critical",
  error: "border-severity-high bg-severity-high-tint text-severity-high",
  warning: "border-severity-medium bg-severity-medium-tint text-severity-medium",
};

const FILTERS = [
  { value: "all", label: "All events" },
  { value: "privilege", label: "Privilege & access" },
  { value: "admin", label: "Portal administration" },
  { value: "project", label: "Project activity" },
  { value: "failed", label: "Failures only" },
];

const LEVELS = [
  { value: "warning", label: "Warnings & errors" },
  { value: "error", label: "Errors only" },
  { value: "critical", label: "Critical only" },
];

// Mirrors the backend's cap: the audit window is classified in memory, so it stays bounded.
const MAX_RANGE_DAYS = 92;

/** YYYY-MM-DD in the admin's own timezone — what <input type="date"> reads and writes. */
const localDay = (d = new Date()) => d.toLocaleDateString("en-CA");

/** Whole local days [from 00:00, to + 1 day 00:00), as the UTC instants the API filters on. */
function toRange(from: string, to: string): DateRange | string {
  const start = new Date(`${from}T00:00`);
  const end = new Date(`${to}T00:00`);
  end.setDate(end.getDate() + 1);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "Pick both dates.";
  if (end <= start) return "The end date must be on or after the start date.";
  if (end.getTime() - start.getTime() > MAX_RANGE_DAYS * 86_400_000)
    return `A range can span at most ${MAX_RANGE_DAYS} days.`;
  return { since: start.toISOString(), until: end.toISOString() };
}

export default function AdminAuditLogPage() {
  const [view, setView] = useState<"audit" | "system">("audit");
  const [from, setFrom] = useState(() => localDay());
  const [to, setTo] = useState(() => localDay());
  const [filter, setFilter] = useState("all");
  const [level, setLevel] = useState<SystemLogLevel>("warning");
  const [search, setSearch] = useState("");
  const [showOverview, setShowOverview] = useState(false);

  const range = toRange(from, to);
  const rangeError = typeof range === "string" ? range : null;
  const validRange = typeof range === "string" ? null : range;

  const category = filter === "all" ? undefined : (filter as AuditFilter);
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.auditLogs(validRange?.since ?? "", validRange?.until ?? "", category),
    queryFn: () => listAuditLogs({ ...validRange!, category }),
    enabled: view === "audit" && validRange !== null,
  });
  const system = useQuery({
    queryKey: queryKeys.admin.systemLogs(validRange?.since ?? "", validRange?.until ?? "", level),
    queryFn: () => listSystemLogs({ ...validRange!, level }),
    enabled: view === "system" && validRange !== null,
  });

  // Search is client-side over the loaded window — the window is already the unit this page
  // fetches, so a server round-trip per keystroke would buy nothing.
  const q = search.trim().toLowerCase();
  const items = (data?.items ?? []).filter(
    (log) =>
      !q ||
      formatAuditAction(log.action).toLowerCase().includes(q) ||
      (log.actor_email ?? log.actor_type).toLowerCase().includes(q) ||
      (log.project_name ?? "").toLowerCase().includes(q) ||
      (log.ip_address ?? "").includes(q)
  );
  const systemItems = (system.data?.items ?? []).filter(
    (log) => !q || log.message.toLowerCase().includes(q) || log.logger.toLowerCase().includes(q)
  );

  const counts = data?.counts;
  const windowLabel = from === to ? from : `${from} → ${to}`;
  const loaded = view === "audit" ? data : system.data;
  const truncated = (loaded?.total ?? 0) > (loaded?.items.length ?? 0);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Administration / Audit"
        title="Audit Log"
        description="Immutable record of security-relevant administrative actions, authentications, and policy modifications — plus the backend's own warnings and errors."
        actions={
          view === "audit" && (
            <Button
              size="sm"
              variant={showOverview ? "secondary" : "outline"}
              onClick={() => setShowOverview((v) => !v)}
              aria-pressed={showOverview}
            >
              <BarChart3 />
              {showOverview ? "Hide overview" : "Overview"}
            </Button>
          )
        }
      />

      <div className="flex flex-wrap items-end gap-3">
        <div className="flex gap-1 rounded-lg border border-border p-0.5">
          <Button size="sm" variant={view === "audit" ? "secondary" : "ghost"} onClick={() => setView("audit")}>
            Audit trail
          </Button>
          <Button size="sm" variant={view === "system" ? "secondary" : "ghost"} onClick={() => setView("system")}>
            System logs
          </Button>
        </div>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          From
          <Input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} className="w-40" />
        </label>
        <label className="flex flex-col gap-1 text-xs text-muted-foreground">
          To
          <Input
            type="date"
            value={to}
            min={from}
            max={localDay()}
            onChange={(e) => setTo(e.target.value)}
            className="w-40"
          />
        </label>
        {rangeError && <p className="pb-1.5 text-xs text-destructive">{rangeError}</p>}
      </div>

      {view === "audit" && showOverview && (
        <MetricStrip
          isLoading={isLoading}
          metrics={[
            {
              label: "Total events",
              value: (counts?.total ?? 0).toLocaleString(),
              hint: windowLabel,
            },
            {
              label: "Privilege & access",
              value: (counts?.privilege ?? 0).toLocaleString(),
              hint: "Sign-ins, roles, members, keys, credentials",
              tone: "high" as const,
            },
            {
              label: "Portal administration",
              value: (counts?.admin ?? 0).toLocaleString(),
              hint: "Workspace-wide, no single project",
            },
            {
              label: "Project activity",
              value: (counts?.project ?? 0).toLocaleString(),
              hint: "Scans, audits, fixes, project policy",
              tone: "signal" as const,
            },
            {
              label: "Failures",
              value: (counts?.failed ?? 0).toLocaleString(),
              hint: "Counted across all three categories",
              tone: (counts?.failed ?? 0) > 0 ? ("critical" as const) : ("default" as const),
            },
          ]}
          className="lg:grid-cols-5"
        />
      )}

      <FilterBar
        search={search}
        onSearchChange={setSearch}
        searchPlaceholder={view === "audit" ? "Action, actor, project or IP…" : "Message or source…"}
        facets={[
          view === "audit"
            ? { type: "select", value: filter, onChange: setFilter, placeholder: "Category", options: FILTERS }
            : {
                type: "select",
                value: level,
                onChange: (v) => setLevel(v as SystemLogLevel),
                placeholder: "Level",
                options: LEVELS,
              },
        ]}
      />

      {view === "system" ? (
        <DataTableCard
          isLoading={system.isLoading}
          isError={system.isError}
          errorMessage="Failed to load system logs."
          isEmpty={systemItems.length === 0}
          emptyState={
            q && (system.data?.items.length ?? 0) > 0 ? (
              <EmptyState
                icon={ServerCrash}
                title="No system logs match your search"
                description="Nothing in the loaded range matches that text. Clear the search to see the full range."
              />
            ) : (
              <EmptyState
                icon={ServerCrash}
                title="No system logs in this range"
                description={`No backend warnings or errors were recorded for ${windowLabel}. Only warnings and above are stored, for 90 days.`}
              />
            )
          }
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">Timestamp</TableHead>
                <TableHead className="py-2.5">Level</TableHead>
                <TableHead className="py-2.5">Source</TableHead>
                <TableHead className="py-2.5">Message</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {systemItems.map((log) => (
                <TableRow key={log.id} className="align-top text-xs">
                  <TableCell className="font-mono text-[11px] text-muted-foreground whitespace-nowrap">
                    {new Date(log.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    <span className={cn("legend rounded-sm border-l-2 px-1.5 py-0.5", LEVEL_TAG[log.level])}>
                      {log.level}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-[11px] text-muted-foreground">{log.logger}</TableCell>
                  <TableCell className="max-w-xl whitespace-normal break-words text-foreground">
                    {log.message}
                    {Object.keys(log.context).length > 0 && (
                      <span className="block font-mono text-[10px] text-muted-foreground">
                        {Object.entries(log.context)
                          .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
                          .join("  ")}
                      </span>
                    )}
                    {log.exception && (
                      <details className="mt-1">
                        <summary className="cursor-pointer text-[11px] text-muted-foreground">Stack trace</summary>
                        <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-muted-foreground">
                          {log.exception}
                        </pre>
                      </details>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      ) : (
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load audit log."
          isEmpty={items.length === 0}
          emptyState={
            q && (data?.items.length ?? 0) > 0 ? (
              <EmptyState
                icon={ScrollText}
                title="No audit events match your search"
                description="Nothing in the loaded range matches that text. Clear the search to see the full range."
              />
            ) : (
              <EmptyState
                icon={ScrollText}
                title="No audit events in this range"
                description={`Nothing matching was recorded for ${windowLabel}. Widen the date range to look further back.`}
              />
            )
          }
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">Timestamp</TableHead>
                <TableHead className="py-2.5">Actor Identity</TableHead>
                <TableHead className="py-2.5">Security Action</TableHead>
                <TableHead className="py-2.5">Category</TableHead>
                <TableHead className="py-2.5">Scope</TableHead>
                <TableHead className="py-2.5">Origin IP</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((log) => (
                <TableRow key={log.id} className="text-xs">
                  <TableCell className="font-mono text-[11px] text-muted-foreground whitespace-nowrap">
                    {new Date(log.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell className="font-mono text-xs font-semibold text-foreground">
                    {log.actor_email ?? log.actor_type}
                    {log.actor_email && log.actor_type !== "user" && (
                      <span className="block font-mono text-[10px] font-normal text-muted-foreground">
                        {log.actor_type}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="font-medium text-foreground">
                    {formatAuditAction(log.action)}
                    {auditDetail(log) && (
                      <span className="block font-mono text-[10px] font-normal text-muted-foreground">
                        {auditDetail(log)}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        "legend rounded-sm border-l-2 px-1.5 py-0.5",
                        CATEGORY_TAG[log.category]
                      )}
                    >
                      {CATEGORY_LABEL[log.category]}
                    </span>
                  </TableCell>
                  <TableCell className="text-[11px] text-muted-foreground">
                    {!log.project_id ? (
                      "Portal-wide"
                    ) : log.project_name ? (
                      <Link
                        href={`/projects/${log.project_id}`}
                        className="underline-offset-4 hover:text-signal hover:underline"
                      >
                        {log.project_name}
                      </Link>
                    ) : (
                      // No name means the project is gone. Audit rows outlive their subject, so
                      // keep the id as the record of what was acted on — but don't link to a
                      // page that can only 404.
                      <span className="font-mono">
                        {log.project_id}
                        <span className="block not-italic opacity-70">deleted project</span>
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-[11px] text-muted-foreground">
                    {log.ip_address ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      )}

      {truncated && (
        // Say what was dropped rather than letting a silently-cut list read as the whole
        // range. ponytail: no pager yet — narrow the range or the filter instead.
        <p className="text-xs text-muted-foreground">
          Showing the {loaded?.items.length.toLocaleString()} most recent of{" "}
          {loaded?.total.toLocaleString()} matching events. Narrow the date range or the filter to
          see the rest.
        </p>
      )}
    </div>
  );
}

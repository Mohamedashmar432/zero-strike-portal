"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, ScrollText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { MetricStrip } from "@/components/common/metric-strip";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  formatAuditAction,
  listAuditLogs,
  type AuditCategory,
  type AuditFilter,
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

const WINDOWS = [
  { value: "1", label: "Last 24 hours" },
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
];

const FILTERS = [
  { value: "all", label: "All events" },
  { value: "privilege", label: "Privilege & access" },
  { value: "admin", label: "Portal administration" },
  { value: "project", label: "Project activity" },
  { value: "failed", label: "Failures only" },
];

export default function AdminAuditLogPage() {
  const [days, setDays] = useState("1");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [showOverview, setShowOverview] = useState(false);

  const category = filter === "all" ? undefined : (filter as AuditFilter);
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.auditLogs(Number(days), category),
    queryFn: () => listAuditLogs({ days: Number(days), category }),
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

  const counts = data?.counts;
  const windowLabel = WINDOWS.find((w) => w.value === days)?.label ?? "window";
  const truncated = (data?.total ?? 0) > (data?.items.length ?? 0);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Administration / Audit"
        title="Audit Log"
        description="Immutable record of security-relevant administrative actions, authentications, and policy modifications."
        actions={
          <Button
            size="sm"
            variant={showOverview ? "secondary" : "outline"}
            onClick={() => setShowOverview((v) => !v)}
            aria-pressed={showOverview}
          >
            <BarChart3 />
            {showOverview ? "Hide overview" : "Overview"}
          </Button>
        }
      />

      {showOverview && (
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
        searchPlaceholder="Action, actor, project or IP…"
        facets={[
          { type: "select", value: days, onChange: setDays, placeholder: "Window", options: WINDOWS },
          { type: "select", value: filter, onChange: setFilter, placeholder: "Category", options: FILTERS },
        ]}
      />

      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load audit log."
        isEmpty={items.length === 0}
        emptyState={
          <EmptyState
            icon={ScrollText}
            title="No audit events in this window"
            description={`Nothing matching was recorded in the ${windowLabel.toLowerCase()}. Widen the window to look further back.`}
          />
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

      {truncated && (
        // Say what was dropped rather than letting a silently-cut list read as the whole
        // window. ponytail: no pager yet — narrow the window or the category instead.
        <p className="text-xs text-muted-foreground">
          Showing the {data?.items.length.toLocaleString()} most recent of{" "}
          {data?.total.toLocaleString()} matching events. Narrow the window or the category to
          see the rest.
        </p>
      )}
    </div>
  );
}

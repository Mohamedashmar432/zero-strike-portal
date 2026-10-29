"use client";

import { Pencil } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { CloudScanLimitEditor } from "@/components/projects/cloud-scan-quota-pill";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { quotaTone, type ProjectInsights, type ProjectInsightsRow, type ScanCounts } from "@/lib/api/project-insights";
import { cn } from "@/lib/utils";
import { fmt, when } from "./date-range";
import { NewCvesCell } from "./new-cves-cell";

const failures = (p: ProjectInsightsRow) => p.cloud.failed + p.cicd.failed;

function Counts({ c }: { c: ScanCounts }) {
  return (
    <span className="font-mono tabular-nums" title={`${c.total} total, ${c.active} active`}>
      {fmt(c.completed)}
      <span className="text-muted-foreground"> / </span>
      <span className={cn(c.failed > 0 ? "text-severity-critical" : "text-muted-foreground")}>{fmt(c.failed)}</span>
    </span>
  );
}

export function ProjectsTab({
  data,
  isLoading,
  isError,
  onOpenActivity,
}: {
  data: ProjectInsights | undefined;
  isLoading: boolean;
  isError: boolean;
  onOpenActivity: (projectId: string) => void;
}) {
  const [sortByFailures, setSortByFailures] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const projects = [...(data?.projects ?? [])];
  if (sortByFailures) projects.sort((a, b) => failures(b) - failures(a));

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {fmt(data?.totals.projects_created ?? 0)} project{data?.totals.projects_created === 1 ? "" : "s"} created in
          this window. Select a row to see that project&apos;s activity.
        </p>
        <Button
          size="sm"
          variant={sortByFailures ? "secondary" : "outline"}
          aria-pressed={sortByFailures}
          onClick={() => setSortByFailures((v) => !v)}
        >
          Sort by failures
        </Button>
      </div>
      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load project insights."
        isEmpty={projects.length === 0}
        emptyState={<EmptyState title="No projects" description="No onboarded projects exist yet." />}
      >
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 text-xs">
              <TableHead className="py-2.5">Project</TableHead>
              <TableHead className="py-2.5">Repos</TableHead>
              <TableHead className="py-2.5">Members</TableHead>
              <TableHead className="py-2.5" title="Distinct users active in this window">
                Active users
              </TableHead>
              <TableHead className="py-2.5" title="completed / failed">
                Cloud scans
              </TableHead>
              <TableHead className="py-2.5" title="completed / failed">
                Pipeline runs
              </TableHead>
              <TableHead className="py-2.5">Cloud quota</TableHead>
              <TableHead className="py-2.5" title="Advisory ids first seen in this window (OSV.dev lookups)">
                New CVEs
              </TableHead>
              <TableHead className="py-2.5">Last error</TableHead>
              <TableHead className="py-2.5">Last scan</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {projects.map((p) => {
              const tone = quotaTone(p.cloud_scan_quota);
              return (
                <TableRow
                  key={p.project_id}
                  className="cursor-pointer align-top text-xs"
                  onClick={() => onOpenActivity(p.project_id)}
                >
                  <TableCell className="font-medium text-foreground">
                    <Link
                      href={`/projects/${p.project_id}`}
                      className="hover:underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {p.name}
                    </Link>
                    {p.is_archived && <span className="legend ml-1.5 text-muted-foreground">archived</span>}
                  </TableCell>
                  <TableCell className="font-mono tabular-nums">{fmt(p.repos)}</TableCell>
                  <TableCell className="font-mono tabular-nums">{fmt(p.members)}</TableCell>
                  <TableCell className="font-mono tabular-nums">{fmt(p.active_users)}</TableCell>
                  <TableCell>
                    <Counts c={p.cloud} />
                  </TableCell>
                  <TableCell>
                    <Counts c={p.cicd} />
                  </TableCell>
                  <TableCell onClick={(e) => e.stopPropagation()}>
                    {editingId === p.project_id ? (
                      <CloudScanLimitEditor
                        projectId={p.project_id}
                        quota={p.cloud_scan_quota}
                        onDone={() => setEditingId(null)}
                      />
                    ) : (
                      <span className="flex items-center gap-1">
                        <span
                          className={cn(
                            "font-mono tabular-nums",
                            tone === "warn" && "text-severity-medium",
                            tone === "full" && "text-severity-critical"
                          )}
                          title={p.cloud_scan_quota.is_default ? "Workspace default limit" : "Project limit"}
                        >
                          {p.cloud_scan_quota.used}/{p.cloud_scan_quota.limit}
                        </span>
                        <Button
                          variant="ghost"
                          size="icon-xs"
                          aria-label={`Edit cloud scan limit for ${p.name}`}
                          onClick={() => setEditingId(p.project_id)}
                        >
                          <Pencil />
                        </Button>
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="max-w-64 truncate">
                    <NewCvesCell cves={p.new_cves} />
                  </TableCell>
                  <TableCell
                    className="max-w-64 truncate font-mono text-severity-critical"
                    title={p.last_error?.message ?? undefined}
                  >
                    {p.last_error ? (
                      (p.last_error.message ?? "No error message was recorded.")
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap font-mono text-muted-foreground">
                    {when(p.last_scan_at)}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

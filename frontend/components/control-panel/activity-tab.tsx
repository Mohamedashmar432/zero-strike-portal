"use client";

import { useQuery } from "@tanstack/react-query";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { SectionRule } from "@/components/layout/section-rule";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getProjectActivity, type InsightsRange } from "@/lib/api/project-insights";
import { queryKeys } from "@/lib/api/query-keys";
import { fmt, when } from "./date-range";
import { RequestsTable } from "./requests-table";

const NONE = "none"; // sentinel for "no project chosen"; FilterBar maps it to its label.

export function ActivityTab({
  range,
  projectId,
  projects,
  onProjectChange,
}: {
  range: InsightsRange | null;
  projectId: string | null;
  projects: { project_id: string; name: string }[];
  onProjectChange: (projectId: string | null) => void;
}) {
  const activity = useQuery({
    queryKey: queryKeys.admin.projectActivity(projectId ?? "", range?.since ?? "", range?.until ?? ""),
    queryFn: () => getProjectActivity(projectId!, range!),
    enabled: range !== null && projectId !== null,
  });

  return (
    <div className="space-y-6">
      <FilterBar
        facets={[
          {
            type: "select",
            value: projectId ?? NONE,
            onChange: (v) => onProjectChange(v === NONE ? null : v),
            placeholder: "Project",
            options: [
              { value: NONE, label: "Select a project" },
              ...projects.map((p) => ({ value: p.project_id, label: p.name })),
            ],
          },
        ]}
      />

      {projectId === null ? (
        <EmptyState
          title="Pick a project"
          description="Choose a project to see who used it, what happened in it, and what failed — or select a row on the Projects tab."
        />
      ) : (
        <>
          <SectionRule label="Active users" />
          <DataTableCard
            isLoading={activity.isLoading}
            isError={activity.isError}
            errorMessage="Failed to load this project's activity."
            isEmpty={(activity.data?.active_users.length ?? 0) === 0}
            emptyState={
              <EmptyState title="No active users" description="Nobody used this project in the selected window." />
            }
          >
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 text-xs">
                  <TableHead className="py-2.5">User</TableHead>
                  <TableHead className="py-2.5">Email</TableHead>
                  <TableHead className="py-2.5">Days active</TableHead>
                  <TableHead className="py-2.5">Last seen</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activity.data?.active_users.map((u) => (
                  <TableRow key={u.user_id} className="text-xs">
                    <TableCell className="font-medium text-foreground">{u.name ?? "—"}</TableCell>
                    <TableCell className="text-muted-foreground">{u.email}</TableCell>
                    <TableCell className="font-mono tabular-nums">{fmt(u.days_active)}</TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-muted-foreground">
                      {when(u.last_seen_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DataTableCard>

          <SectionRule label="Timeline" />
          <DataTableCard
            isLoading={activity.isLoading}
            isError={activity.isError}
            errorMessage="Failed to load this project's timeline."
            isEmpty={(activity.data?.timeline.length ?? 0) === 0}
            emptyState={
              <EmptyState title="No recorded events" description="The audit log has nothing for this project in the window." />
            }
          >
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 text-xs">
                  <TableHead className="py-2.5">When</TableHead>
                  <TableHead className="py-2.5">Action</TableHead>
                  <TableHead className="py-2.5">Actor</TableHead>
                  <TableHead className="py-2.5">Target</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activity.data?.timeline.map((e, i) => (
                  <TableRow key={`${e.at}-${i}`} className="align-top text-xs">
                    <TableCell className="whitespace-nowrap font-mono text-muted-foreground">{when(e.at)}</TableCell>
                    <TableCell
                      className="font-medium text-foreground"
                      title={e.metadata ? JSON.stringify(e.metadata) : undefined}
                    >
                      {e.action}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {e.actor_type === "user" ? (e.actor_email ?? "user") : (e.actor_email ?? e.actor_type)}
                      {e.actor_type !== "user" && <span className="legend ml-1.5">{e.actor_type}</span>}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground">
                      {e.target_type ? `${e.target_type}${e.target_id ? ` ${e.target_id}` : ""}` : "—"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DataTableCard>

          <SectionRule label="Requests & errors" />
          <RequestsTable key={projectId} range={range} fixedProjectId={projectId} />
        </>
      )}
    </div>
  );
}

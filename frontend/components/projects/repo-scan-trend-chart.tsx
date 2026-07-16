"use client";

import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { EmptyState } from "@/components/common/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { listProjectRepos } from "@/lib/api/project-repos";
import { getRepoScanHistory } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";

const chartConfig: ChartConfig = {
  total: { label: "Findings", color: "var(--primary)" },
};

// Single chart, one repo at a time — a picker swaps which connected repo's scan history
// (findings count per scan, oldest to newest) is plotted, so the last-scan-vs-recent-scan
// trend is comparable per repo instead of blended across a whole multi-repo project.
export function RepoScanTrendChart({ projectId }: { projectId: string }) {
  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });
  const [selectedRepoId, setSelectedRepoId] = useState<string>();
  const repoId = selectedRepoId ?? repos?.[0]?.id;

  const { data: history, isLoading } = useQuery({
    queryKey: queryKeys.projects.repoScanHistory(projectId, repoId ?? ""),
    queryFn: () => getRepoScanHistory(projectId, repoId!),
    enabled: !!repoId,
  });

  const chartData = useMemo(
    () =>
      (history ?? []).map((h) => ({
        label: new Date(h.created_at).toLocaleDateString(undefined, { month: "numeric", day: "numeric" }),
        total: h.total_findings,
      })),
    [history]
  );

  if (!repos) return <Skeleton className="h-[220px] w-full" />;
  if (repos.length === 0) {
    return <EmptyState title="No repositories connected" description="Connect a repo to track its scan history." />;
  }

  return (
    <div className="space-y-3">
      <Select value={repoId} onValueChange={(v) => setSelectedRepoId(v ?? undefined)}>
        <SelectTrigger size="sm" className="w-full sm:w-64">
          <SelectValue placeholder="Select a repository" />
        </SelectTrigger>
        <SelectContent>
          {repos.map((r) => (
            <SelectItem key={r.id} value={r.id}>
              {r.label || r.repo_full_name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      {isLoading ? (
        <Skeleton className="h-[220px] w-full" />
      ) : chartData.length === 0 ? (
        <EmptyState title="Not enough scan history yet" description="Run more scans on this repo to see a trend." />
      ) : (
        <ChartContainer config={chartConfig} className="h-[220px] w-full">
          <BarChart data={chartData}>
            <CartesianGrid vertical={false} strokeDasharray="3 3" />
            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Bar dataKey="total" fill="var(--color-total)" radius={4} />
          </BarChart>
        </ChartContainer>
      )}
    </div>
  );
}

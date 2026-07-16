"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { EmptyState } from "@/components/common/empty-state";
import { projectRiskStatus, SeverityCountPills } from "@/components/severity/severity-count-pills";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { SeverityCounts } from "@/lib/api/dashboard";
import { listProjectRepos } from "@/lib/api/project-repos";
import { queryKeys } from "@/lib/api/query-keys";
import { getReport } from "@/lib/api/reports";
import { listScans, type Scan } from "@/lib/api/scans";

const EMPTY_COUNTS: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };

/**
 * Shows a project's connected repos with per-repo severity/status/last-scan.
 *
 * Only cloud scans record a `repo_url`, matched here against each repo's
 * `clone_url` — local/CI scans can't be attributed to a specific connected repo
 * with the data this app tracks today, so a repo with only local/CI scan history
 * shows as "No scans yet" rather than a guessed status.
 */
export function ProjectRepoBreakdown({ projectId }: { projectId: string }) {
  const { data: repos, isLoading: reposLoading } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });
  const { data: scansPage, isLoading: scansLoading } = useQuery({
    queryKey: ["projects", projectId, "scans", "for-repo-breakdown"],
    queryFn: () => listScans(projectId, 1, 50),
  });

  const latestScanByRepo = new Map<string, Scan>();
  for (const scan of scansPage?.items ?? []) {
    if (!scan.repo_url) continue;
    for (const repo of repos ?? []) {
      if (repo.clone_url === scan.repo_url) {
        const existing = latestScanByRepo.get(repo.id);
        if (!existing || new Date(scan.created_at) > new Date(existing.created_at)) {
          latestScanByRepo.set(repo.id, scan);
        }
      }
    }
  }
  const matchedScans = (repos ?? []).map((r) => latestScanByRepo.get(r.id) ?? null);

  const reportQueries = useQueries({
    queries: matchedScans.map((scan) => ({
      queryKey: queryKeys.scans.report(scan?.id ?? ""),
      queryFn: () => getReport(scan!.id),
      enabled: !!scan && scan.status === "completed",
      retry: false,
    })),
  });

  if (reposLoading || scansLoading) return <Skeleton className="h-16 w-full" />;

  if (!repos || repos.length === 0) {
    return (
      <EmptyState
        title="No repositories connected"
        description="Connect a repo on this project's Repositories tab to see it here."
      />
    );
  }

  return (
    <div className="space-y-2">
      {repos.map((repo, i) => {
        const scan = matchedScans[i];
        const report = reportQueries[i]?.data;
        const counts: SeverityCounts = report
          ? {
              critical: report.stats.by_severity.critical ?? 0,
              high: report.stats.by_severity.high ?? 0,
              medium: report.stats.by_severity.medium ?? 0,
              low: report.stats.by_severity.low ?? 0,
              info: report.stats.by_severity.info ?? 0,
            }
          : EMPTY_COUNTS;
        const risk = projectRiskStatus(counts);
        return (
          <div
            key={repo.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border/60 bg-background px-3 py-2"
          >
            <div className="min-w-0">
              <p className="truncate font-mono text-sm">
                {repo.label ? `${repo.label} — ${repo.repo_full_name}` : repo.repo_full_name}
              </p>
              <p className="text-xs text-muted-foreground">{repo.selected_branch}</p>
            </div>
            <div className="flex flex-wrap items-center gap-4">
              <SeverityCountPills counts={counts} />
              {scan ? (
                <span className={cn("rounded-sm px-2 py-0.5 text-xs font-medium", risk.className)}>
                  {risk.label}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">No scans yet</span>
              )}
              <span className="text-xs text-muted-foreground">
                {scan ? new Date(scan.created_at).toLocaleDateString() : "—"}
              </span>
              {scan && (
                <Link
                  href={`/projects/${projectId}/scans/${scan.id}`}
                  className="text-xs font-medium text-primary hover:underline"
                >
                  View
                </Link>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  Calendar,
  CheckCircle2,
  FolderGit2,
  GitBranch,
  Shield,
  ShieldAlert,
} from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/common/empty-state";
import { projectRiskStatus, SeverityCountPills } from "@/components/severity/severity-count-pills";
import { SeveritySpectrum } from "@/components/severity/severity-spectrum";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { SeverityCounts } from "@/lib/api/dashboard";
import { listProjectRepos } from "@/lib/api/project-repos";
import { queryKeys } from "@/lib/api/query-keys";
import { getReport } from "@/lib/api/reports";
import { listScans, type Scan } from "@/lib/api/scans";

const EMPTY_COUNTS: SeverityCounts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };

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

  if (reposLoading || scansLoading) {
    return (
      <div className="space-y-2 py-1">
        <Skeleton className="h-16 w-full rounded-xl" />
      </div>
    );
  }

  if (!repos || repos.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-border/80 bg-background/50 p-6 text-center text-xs">
        <FolderGit2 className="mx-auto size-6 text-muted-foreground/50 mb-1.5" />
        <p className="font-medium text-foreground">No repositories linked to this project</p>
        <p className="text-muted-foreground text-[11px] mt-0.5">
          Connect a GitHub or Azure DevOps repository on the project settings tab.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2.5">
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
        const risk = projectRiskStatus(counts, scan?.status ?? "none");
        const edge =
          counts.critical > 0
            ? "border-l-severity-critical"
            : counts.high > 0
              ? "border-l-severity-high"
              : counts.medium > 0
                ? "border-l-severity-medium"
                : "border-l-status-success";

        return (
          <div
            key={repo.id}
            className={cn(
              "flex flex-col gap-3 rounded-sm border border-border border-l-2 bg-background p-3.5 transition-colors duration-200 hover:border-muted-foreground/40 sm:flex-row sm:items-center sm:justify-between",
              edge
            )}
          >
            {/* Left Repository Metadata */}
            <div className="space-y-1.5 min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex size-6 shrink-0 items-center justify-center rounded-sm bg-muted text-muted-foreground">
                  <FolderGit2 className="size-3.5" />
                </div>
                <span className="font-mono text-xs font-bold text-foreground truncate">
                  {repo.repo_full_name}
                </span>
                <Badge variant="outline" className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                  {repo.provider}
                </Badge>
                <div className="flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                  <GitBranch className="size-3 text-muted-foreground/80" />
                  <span>{repo.selected_branch || "main"}</span>
                </div>
              </div>

              {repo.label && (
                <p className="text-[11px] text-muted-foreground font-mono pl-8 line-clamp-1">
                  Label: <span className="text-foreground/80">{repo.label}</span>
                </p>
              )}
            </div>

            {/* Right Status & Scan Details */}
            <div className="flex flex-wrap items-center gap-3 shrink-0 pt-2 sm:pt-0 border-t border-border/40 sm:border-t-0">
              {/* Finding Severity Counts */}
              <div className="flex shrink-0 flex-col gap-1.5">
                {/* "none" when the repo has never been scanned: without a sentinel
                    the zero counts render a green "Clean" right next to this
                    row's own "No Scans" badge — a contradiction, and a false
                    all-clear on a repo nobody has actually looked at. */}
                <SeveritySpectrum counts={counts} className="w-32" scanStatus={scan?.status ?? "none"} />
                <SeverityCountPills counts={counts} scanStatus={scan?.status ?? "none"} />
              </div>

              {/* Health Risk Badge */}
              {scan ? (
                <Badge
                  variant="outline"
                  className={cn("font-mono text-[10px] font-semibold uppercase", risk.className)}
                >
                  {risk.label}
                </Badge>
              ) : (
                <Badge variant="secondary" className="font-mono text-[10px] text-muted-foreground">
                  No Scans
                </Badge>
              )}

              {/* Timestamp */}
              <div className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                <Calendar className="size-3 opacity-60" />
                <span>{scan ? new Date(scan.created_at).toLocaleDateString() : "—"}</span>
              </div>

              {/* Direct View Action */}
              {scan && (
                <Button
                  nativeButton={false}
                  render={<Link href={`/projects/${projectId}/scans/${scan.id}`} />}
                  size="xs"
                  variant="outline"
                  className="gap-1 font-medium text-xs h-7 border-border/80 hover:bg-muted hover:text-foreground"
                >
                  <span>View Scan</span>
                  <ArrowRight className="size-3" />
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

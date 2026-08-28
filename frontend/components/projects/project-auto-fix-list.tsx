"use client";

import { useQuery } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import Link from "next/link";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  listProjectAutoFix,
  type AutoFixRiskRating,
  type ProjectAutoFixScanItem,
} from "@/lib/api/auto-fix";
import { refetchWhileAnyItemActive } from "@/lib/api/polling";
import { listProjectRepos } from "@/lib/api/project-repos";
import { queryKeys } from "@/lib/api/query-keys";

const RISK_TONE: Record<AutoFixRiskRating, string> = {
  critical: "bg-severity-critical/15 text-severity-critical border-severity-critical/30",
  high: "bg-severity-high/15 text-severity-high border-severity-high/30",
  medium: "bg-severity-medium/15 text-severity-medium border-severity-medium/30",
  low: "bg-severity-low/15 text-severity-low border-severity-low/30",
  none: "",
};

function RiskBadge({ rating }: { rating: AutoFixRiskRating }) {
  if (rating === "none") return <span className="text-muted-foreground">—</span>;
  return (
    <Badge variant="outline" className={RISK_TONE[rating]}>
      {rating}
    </Badge>
  );
}

/** The dedicated Auto-Fix section: every scan sent to Auto-Fix, listed like the Scans tab.
 * Clicking a row opens the dedicated fix report page. */
export function ProjectAutoFixList({ projectId }: { projectId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.ai.autofix.projectList(projectId),
    queryFn: () => listProjectAutoFix(projectId),
    refetchInterval: refetchWhileAnyItemActive<ProjectAutoFixScanItem>(),
  });

  // Shared cache with the Repositories/Scans tabs — resolve a friendly repo label.
  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });
  const repoById = new Map((repos ?? []).map((r) => [r.id, r]));
  function repoLabel(item: ProjectAutoFixScanItem) {
    const repo = item.project_repo_id ? repoById.get(item.project_repo_id) : undefined;
    if (repo) return repo.label || repo.repo_full_name;
    return item.repo_url ?? "—";
  }

  const items = data?.items ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold">Auto-Fix</h2>
        <p className="max-w-2xl text-sm text-muted-foreground">
          Scans you sent to Auto-Fix. Open one to review AI-generated patch proposals — you review every
          diff and nothing auto-commits.
        </p>
      </div>
      <DataTableCard
        isLoading={isLoading}
        isError={false}
        isEmpty={items.length === 0}
        emptyState={
          <EmptyState
            icon={Wand2}
            title="No Auto-Fix runs yet"
            description="Open a completed scan and click “Auto-Fix” (or Generate Fix on a finding) to send it here."
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Repository</TableHead>
              <TableHead>AI status</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Breakdown</TableHead>
              <TableHead>PRs</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.scan_id}>
                <TableCell>{item.scan_type ? <ScanTypeBadge scanType={item.scan_type} /> : "—"}</TableCell>
                <TableCell className="max-w-48 truncate font-mono text-xs" title={repoLabel(item)}>
                  {repoLabel(item)}
                </TableCell>
                <TableCell>
                  <AiStatusBadge
                    kind="autofix"
                    status={item.status}
                    startedAt={item.started_at}
                    progressCompleted={item.progress_completed}
                    progressTotal={item.progress_total}
                  />
                </TableCell>
                <TableCell>
                  <RiskBadge rating={item.summary.risk_rating} />
                </TableCell>
                <TableCell className="text-xs tabular-nums text-muted-foreground">
                  <span className="text-status-success">{item.summary.ai_fixable} fixable</span>
                  {" · "}
                  <span>{item.summary.needs_review_on_fix} review</span>
                  {" · "}
                  <span>{item.summary.cannot_fix} manual</span>
                </TableCell>
                <TableCell className="tabular-nums">{item.summary.pr_created}</TableCell>
                <TableCell>
                  <Button
                    variant="outline"
                    size="sm"
                    nativeButton={false}
                    render={<Link href={`/projects/${projectId}/auto-fix/${item.scan_id}`} />}
                  >
                    Review
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

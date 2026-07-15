"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { OwaspChart } from "@/components/common/owasp-chart";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { listProjectRepos } from "@/lib/api/project-repos";
import { getProjectOwaspSummary } from "@/lib/api/projects";
import { owaspChartData } from "@/lib/owasp";

const ALL_REPOS = "__all__";

// A repo-scope selector (overall project vs. one specific repo) driving the OWASP
// compliance chart — decorative here (no findings list on this tab to filter into).
export function ProjectOwaspSection({ projectId }: { projectId: string }) {
  const { data: repos } = useQuery({
    queryKey: ["projects", projectId, "repos"],
    queryFn: () => listProjectRepos(projectId),
  });
  const [scope, setScope] = useState<string>(ALL_REPOS);
  const projectRepoId = scope === ALL_REPOS ? undefined : scope;

  const { data: summary, isLoading } = useQuery({
    queryKey: ["projects", projectId, "owasp-summary", projectRepoId ?? ""],
    queryFn: () => getProjectOwaspSummary(projectId, projectRepoId),
  });

  return (
    <div className="space-y-3">
      <Select value={scope} onValueChange={(v) => setScope(v ?? ALL_REPOS)}>
        <SelectTrigger size="sm" className="w-full sm:w-64">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL_REPOS}>All repositories</SelectItem>
          {repos?.map((r) => (
            <SelectItem key={r.id} value={r.id}>
              {r.label || r.repo_full_name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <OwaspChart data={owaspChartData(summary?.by_owasp)} activeCategory={undefined} />
      {isLoading && <p className="text-xs text-muted-foreground">Loading…</p>}
    </div>
  );
}

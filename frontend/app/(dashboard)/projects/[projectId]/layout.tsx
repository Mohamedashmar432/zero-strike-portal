"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Suspense } from "react";
import { ProjectSidebar } from "@/components/projects/project-sidebar";
import { Skeleton } from "@/components/ui/skeleton";
import { listMembers } from "@/lib/api/project-members";
import { listProjectRepos } from "@/lib/api/project-repos";
import { getProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";

/**
 * One project shell for every route under /projects/[projectId] — overview tabs, vulnerabilities,
 * scans, audits, auto-fix. The rail used to live inside the overview page only, so opening a scan
 * or a vulnerability dropped it. Queries reuse the pages' own cache keys, so this adds no requests.
 */
export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { projectId } = useParams<{ projectId: string }>();

  const { data: project, isError } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
    // ponytail: errors are rendered by the page itself; the rail just stays absent on 403/404.
    retry: false,
  });
  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
    enabled: !!project,
  });
  const { data: members } = useQuery({
    queryKey: queryKeys.projects.members(projectId),
    queryFn: () => listMembers(projectId),
    enabled: !!project,
  });

  return (
    <div className="flex flex-col items-start gap-5 lg:flex-row">
      <div className="w-full shrink-0 lg:sticky lg:top-4 lg:w-auto">
        {project ? (
          // useSearchParams in the rail needs a Suspense boundary.
          <Suspense fallback={<Skeleton className="h-96 w-full rounded-lg lg:w-56" />}>
            <ProjectSidebar
              project={project}
              counts={{ scans: project.scan_count, repos: repos?.length, members: members?.length }}
            />
          </Suspense>
        ) : (
          // Placeholder only while loading: on a 403/404 it would pulse forever beside the error.
          !isError && <Skeleton className="h-96 w-full rounded-lg lg:w-56" />
        )}
      </div>
      <div className="w-full min-w-0 flex-1">{children}</div>
    </div>
  );
}

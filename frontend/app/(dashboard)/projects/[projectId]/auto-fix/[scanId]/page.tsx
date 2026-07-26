"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams, useSearchParams } from "next/navigation";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { ProjectAutoFixSection } from "@/components/projects/project-auto-fix-section";
import { getProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";

function canManage(role: string | undefined) {
  return role === "owner" || role === "admin";
}

/** Dedicated Auto-Fix report page for one scan — the review surface reached from the Auto-Fix
 * section list (or a per-finding "Generate Fix" deep link ?finding=...). */
export default function AutoFixReportPage() {
  const { projectId, scanId } = useParams<{ projectId: string; scanId: string }>();
  const focusFindingId = useSearchParams().get("finding");

  const { data: project } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });

  return (
    <div className="space-y-6">
      <Breadcrumbs
        items={[
          { label: "Projects", href: "/projects" },
          { label: project?.name ?? projectId, href: `/projects/${projectId}?tab=auto-fix` },
          { label: "Auto-Fix" },
        ]}
      />
      <ProjectAutoFixSection
        scanId={scanId}
        canApprove={canManage(project?.my_role)}
        focusFindingId={focusFindingId}
      />
    </div>
  );
}

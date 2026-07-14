"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { PageHeader } from "@/components/layout/page-header";
import { RepoConnectWizard } from "@/components/repos/repo-connect-wizard";
import { getProject } from "@/lib/api/projects";

export default function AddRepoPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();

  const { data: project } = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => getProject(projectId),
  });

  const backHref = `/projects/${projectId}?tab=repos`;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Add repository"
        description="Connect a GitHub or Azure DevOps repo so cloud scans can reuse it without re-entering a URL or token each time."
        breadcrumb={
          <Breadcrumbs
            items={[
              { label: "Projects", href: "/projects" },
              { label: project?.name ?? "Project", href: `/projects/${projectId}` },
              { label: "Repositories", href: backHref },
              { label: "Add repository" },
            ]}
          />
        }
      />
      <RepoConnectWizard projectId={projectId} cancelHref={backHref} onConnected={() => router.push(backHref)} />
    </div>
  );
}

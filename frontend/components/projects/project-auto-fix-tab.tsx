"use client";

import { useQuery } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/common/empty-state";
import { ProjectAutoFixList } from "@/components/projects/project-auto-fix-list";
import { ProjectAutoFixSection } from "@/components/projects/project-auto-fix-section";
import { getAiStatus } from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";

export function ProjectAutoFixTab({ projectId, canApprove }: { projectId: string; canApprove: boolean }) {
  const params = useSearchParams();
  const scanId = params.get("scan");
  const focusFindingId = params.get("finding");

  const { data: aiStatus } = useQuery({ queryKey: queryKeys.ai.status(), queryFn: getAiStatus });

  if (!(aiStatus?.enabled ?? false)) {
    return (
      <EmptyState
        icon={Wand2}
        title="AI provider not configured"
        description="Configure an AI provider in Settings → AI Provider to enable AI Auto-Fix."
      />
    );
  }
  // Deep-link back-compat: ?scan= renders that scan's proposals inline; otherwise the section list.
  if (scanId) {
    return <ProjectAutoFixSection scanId={scanId} canApprove={canApprove} focusFindingId={focusFindingId} />;
  }
  return <ProjectAutoFixList projectId={projectId} />;
}

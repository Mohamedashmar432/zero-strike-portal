"use client";

import { useQuery } from "@tanstack/react-query";
import { Wand2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { EmptyState } from "@/components/common/empty-state";
import { ProjectAutoFixSection } from "@/components/projects/project-auto-fix-section";
import { getAiStatus } from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";

export function ProjectAutoFixTab({ canApprove }: { canApprove: boolean }) {
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
  if (!scanId) {
    return (
      <EmptyState
        icon={Wand2}
        title="Auto-Fix"
        description="Open a completed scan and click “Auto AI Fix” to generate reviewable patch proposals here. You review every diff — nothing auto-commits."
      />
    );
  }
  return <ProjectAutoFixSection scanId={scanId} canApprove={canApprove} focusFindingId={focusFindingId} />;
}

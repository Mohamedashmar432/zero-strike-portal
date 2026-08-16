"use client";

import { ProjectComplianceFrameworksSection } from "@/components/projects/project-compliance-frameworks-section";

export function ProjectComplianceTab({ projectId }: { projectId: string }) {
  return (
    <div className="space-y-6">
      <ProjectComplianceFrameworksSection projectId={projectId} />
    </div>
  );
}

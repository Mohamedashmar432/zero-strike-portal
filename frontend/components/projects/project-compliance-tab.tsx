"use client";

import { ProjectComplianceFrameworksSection } from "@/components/projects/project-compliance-frameworks-section";
import { ProjectOwaspSection } from "@/components/projects/project-owasp-section";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ProjectComplianceTab({ projectId }: { projectId: string }) {
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">OWASP Top 10 Compliance</CardTitle>
        </CardHeader>
        <CardContent>
          <ProjectOwaspSection projectId={projectId} />
        </CardContent>
      </Card>

      <ProjectComplianceFrameworksSection projectId={projectId} />
    </div>
  );
}

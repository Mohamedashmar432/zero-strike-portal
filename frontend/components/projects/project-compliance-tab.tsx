"use client";

import { ProjectOwaspSection } from "@/components/projects/project-owasp-section";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function ProjectComplianceTab({ projectId }: { projectId: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">OWASP Top 10 Compliance</CardTitle>
      </CardHeader>
      <CardContent>
        <ProjectOwaspSection projectId={projectId} />
      </CardContent>
    </Card>
  );
}

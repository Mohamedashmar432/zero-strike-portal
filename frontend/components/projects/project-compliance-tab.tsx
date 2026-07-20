"use client";

import { Info } from "lucide-react";
import { ProjectComplianceFrameworksSection } from "@/components/projects/project-compliance-frameworks-section";
import { ProjectOwaspSection } from "@/components/projects/project-owasp-section";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
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

      <Alert className="border-blue-500/50 bg-blue-500/5">
        <Info />
        <AlertTitle>Compliance Frameworks are on the roadmap</AlertTitle>
        <AlertDescription>Preview only — not live yet.</AlertDescription>
      </Alert>

      <ProjectComplianceFrameworksSection />
    </div>
  );
}

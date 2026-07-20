"use client";

import { Info } from "lucide-react";
import { ProjectAutoFixSection } from "@/components/projects/project-auto-fix-section";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

export function ProjectAutoFixTab() {
  return (
    <div className="space-y-6">
      <Alert className="border-blue-500/50 bg-blue-500/5">
        <Info />
        <AlertTitle>Auto-Fix is on the roadmap</AlertTitle>
        <AlertDescription>Preview only — not live yet.</AlertDescription>
      </Alert>

      <ProjectAutoFixSection />
    </div>
  );
}

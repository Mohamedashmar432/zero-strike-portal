"use client";

import { ShieldCheck } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const FRAMEWORKS = ["GDPR", "CCPA/CPRA", "SOC 2", "ISO/IEC 27001:2022", "HIPAA Security Rule"];

function notifyRoadmap(feature: string) {
  toast.info(`${feature} isn't available yet`, {
    description: "Automated framework gap analysis is on the roadmap.",
  });
}

export function ProjectComplianceFrameworksSection() {
  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium">Compliance Frameworks</h3>
            <Badge variant="secondary">Planned</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Automated gap analysis against these frameworks is on the roadmap.
          </p>
        </div>
        <Button size="sm" onClick={() => notifyRoadmap("Compliance audit")}>
          <ShieldCheck />
          Run Audit
        </Button>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FRAMEWORKS.map((framework) => (
          <Card key={framework}>
            <CardHeader>
              <CardTitle>{framework}</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">Readiness will appear here once an audit runs.</p>
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={() => notifyRoadmap("Framework details")}
              >
                View Framework Details →
              </Button>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

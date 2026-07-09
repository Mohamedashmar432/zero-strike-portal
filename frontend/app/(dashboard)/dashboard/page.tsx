"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { listProjects } from "@/lib/api/projects";

export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: () => listProjects(1, 100),
  });

  const stats = [
    { label: "Projects", value: data?.total ?? 0 },
    { label: "Scans", value: data?.items.reduce((sum, p) => sum + p.scan_count, 0) ?? 0 },
    { label: "Critical Findings", value: 0, severity: "critical" as const },
    { label: "High Findings", value: 0, severity: "high" as const },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Dashboard</h1>
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.label}>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-normal text-muted-foreground">{stat.label}</CardTitle>
            </CardHeader>
            <CardContent className="flex items-center gap-2">
              {isLoading ? (
                <Skeleton className="h-8 w-12" />
              ) : (
                <span className="font-mono text-2xl font-semibold">{stat.value}</span>
              )}
              {stat.severity && <SeverityBadge severity={stat.severity} />}
            </CardContent>
          </Card>
        ))}
      </div>
      <p className="text-sm text-muted-foreground">
        Recent SAST scans and latest reports will appear here once you run your first scan.
      </p>
    </div>
  );
}

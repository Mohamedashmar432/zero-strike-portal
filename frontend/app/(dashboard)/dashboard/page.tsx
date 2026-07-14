"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { SeverityDistributionChart } from "@/components/dashboard/severity-distribution-chart";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getDashboardStats, type RecentScanItem, type SeverityCounts } from "@/lib/api/dashboard";

const SEVERITY_ORDER: (keyof SeverityCounts)[] = ["critical", "high", "medium", "low", "info"];

function RecentScanSeverities({ counts }: { counts: SeverityCounts }) {
  const nonZero = SEVERITY_ORDER.filter((severity) => counts[severity] > 0);
  if (nonZero.length === 0) return <span className="text-xs text-muted-foreground">No findings</span>;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {nonZero.map((severity) => (
        <span key={severity} className="inline-flex items-center gap-1">
          <SeverityBadge severity={severity} />
          <span className="text-xs text-muted-foreground">{counts[severity]}</span>
        </span>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: getDashboardStats,
  });

  const stats = [
    { label: "Projects", value: data?.project_count ?? 0 },
    { label: "Scans", value: data?.scan_count ?? 0 },
    { label: "Critical Findings", value: data?.findings_by_severity.critical ?? 0, severity: "critical" as const },
    { label: "High Findings", value: data?.findings_by_severity.high ?? 0, severity: "high" as const },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Dashboard" description="Overview of your organization's scans, projects, and findings." />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4 md:gap-6">
        {stats.map((stat) => (
          <Card key={stat.label} className="shadow-sm">
            <CardHeader className="pb-2">
              <CardTitle className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                {stat.label}
              </CardTitle>
            </CardHeader>
            <CardContent className="flex items-center gap-2">
              {isLoading ? (
                <Skeleton className="h-9 w-12" />
              ) : (
                <span className="text-3xl font-semibold tracking-tight">{stat.value}</span>
              )}
              {stat.severity && <SeverityBadge severity={stat.severity} />}
            </CardContent>
          </Card>
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">Severity Distribution</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <Skeleton className="h-[220px] w-full" />
          ) : (
            data && <SeverityDistributionChart data={data.findings_by_severity} />
          )}
        </CardContent>
      </Card>
      <div className="space-y-2">
        <h2 className="text-sm font-normal text-muted-foreground">Recent Scans</h2>
        <DataTableCard
          isLoading={isLoading}
          isError={false}
          isEmpty={(data?.recent_scans.length ?? 0) === 0}
          emptyState={<EmptyState title="No scans yet" description="Run a scan to see it show up here." />}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Findings</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.recent_scans.map((scan: RecentScanItem) => (
                <TableRow key={scan.scan_id}>
                  <TableCell>
                    <Link
                      href={`/projects/${scan.project_id}/scans/${scan.scan_id}`}
                      className="font-medium underline-offset-4 hover:underline"
                    >
                      {scan.project_name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <ScanTypeBadge scanType={scan.scan_type} />
                  </TableCell>
                  <TableCell>
                    <ScanStatusBadge status={scan.status} />
                  </TableCell>
                  <TableCell>
                    <RecentScanSeverities counts={scan.findings_by_severity} />
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(scan.created_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>
    </div>
  );
}

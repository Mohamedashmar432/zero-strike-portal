"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Binary, CheckCircle2, Cpu, RefreshCw, XCircle } from "lucide-react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { StatCard } from "@/components/common/stat-card";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { getScannerStatus } from "@/lib/api/scanner-status";

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function ScannerStatusPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "scanner-status"],
    queryFn: () => getScannerStatus(),
    refetchInterval: 15000,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Scanner Infrastructure"
        description="Published ZeroStrike scanner binaries, cloud scan queue telemetry, and failure logs."
      />

      {data && !data.engine_available && (
        <Alert variant="destructive">
          <XCircle className="size-4" />
          <AlertTitle>Cloud scan engine unavailable on this server</AlertTitle>
          <AlertDescription>
            The scanner binary isn&apos;t resolvable at SCANNER_BINARY_PATH — every cloud scan will
            fail until this is fixed and the backend is restarted. This is separate from the binary
            checklist below, which covers what&apos;s published for external CI/local download.
          </AlertDescription>
        </Alert>
      )}

      {/* Cloud Scan Queue KPIs */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 border-b border-border/60 pb-2">
          <Cpu className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Cloud Execution Queue</h2>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCard label="Active Running Scans" value={data?.queue.running ?? "—"} isLoading={isLoading} />
          <StatCard label="Queued Scans" value={data?.queue.queued ?? "—"} isLoading={isLoading} />
          <StatCard
            label="Worker Concurrency Slots"
            value={data ? `${data.queue.running} / ${data.queue.max_concurrent}` : "—"}
            isLoading={isLoading}
            caption="Server subprocess execution pool"
          />
        </div>
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load queue status."
          isEmpty={!!data && data.queue.running_scans.length === 0}
          emptyState={<EmptyState title="No cloud scans currently running." />}
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">Scan ID</TableHead>
                <TableHead className="py-2.5">Project ID</TableHead>
                <TableHead className="py-2.5">Started At</TableHead>
                <TableHead className="py-2.5" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.queue.running_scans.map((s) => (
                <TableRow key={s.scan_id} className="text-xs">
                  <TableCell className="font-mono text-xs font-semibold text-foreground">{s.scan_id}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{s.project_id}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{formatDate(s.started_at)}</TableCell>
                  <TableCell>
                    {s.stuck && <Badge variant="destructive">Stuck — pending reap</Badge>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>

      {/* Binary Checklist Section */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 border-b border-border/60 pb-2">
          <Binary className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Published Binaries Distribution</h2>
        </div>
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load scanner status."
          isEmpty={false}
          emptyState={<EmptyState title="No data" />}
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">OS / Architecture</TableHead>
                <TableHead className="py-2.5">Distribution Status</TableHead>
                <TableHead className="py-2.5">Version</TableHead>
                <TableHead className="py-2.5">Uploaded</TableHead>
                <TableHead className="py-2.5">Uploaded By</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.binaries.map((b) => (
                <TableRow key={`${b.os}-${b.arch}`} className="text-xs">
                  <TableCell className="font-mono font-semibold text-foreground">
                    {b.os}-{b.arch}
                  </TableCell>
                  <TableCell>
                    {b.published ? (
                      <Badge variant="secondary" className="gap-1 font-mono text-[10px] text-status-success">
                        <CheckCircle2 className="size-3" /> Published
                      </Badge>
                    ) : (
                      <Badge variant="destructive" className="gap-1 font-mono text-[10px]">
                        <XCircle className="size-3" /> Missing
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{b.version ?? "—"}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{formatDate(b.uploaded_at)}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{b.uploaded_by ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>

      {/* Recent Failures Section */}
      <div className="space-y-3">
        <div className="flex items-center gap-2 border-b border-border/60 pb-2">
          <Activity className="size-4 text-muted-foreground" />
          <h2 className="text-sm font-semibold tracking-tight text-foreground">Recent Scan Failures</h2>
        </div>
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load recent failures."
          isEmpty={!!data && data.recent_failures.length === 0}
          emptyState={<EmptyState title="No recent scan failures." />}
        >
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">Project ID</TableHead>
                <TableHead className="py-2.5">Scan Type</TableHead>
                <TableHead className="py-2.5">Error Message</TableHead>
                <TableHead className="py-2.5">Completed</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.recent_failures.map((f) => (
                <TableRow key={f.scan_id} className="text-xs">
                  <TableCell className="font-mono text-xs font-semibold text-foreground">{f.project_id}</TableCell>
                  <TableCell className="font-mono text-xs uppercase text-muted-foreground">{f.scan_type}</TableCell>
                  <TableCell className="max-w-md truncate font-mono text-xs text-severity-critical" title={f.error_message ?? undefined}>
                    {f.error_message ?? "—"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{formatDate(f.completed_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>
    </div>
  );
}

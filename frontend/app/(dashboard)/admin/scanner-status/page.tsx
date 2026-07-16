"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
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
        title="Scanner Status"
        description="Published scanner binaries, the live cloud-scan queue, and recent failures."
      />

      {data && !data.engine_available && (
        <Alert variant="destructive">
          <XCircle />
          <AlertTitle>Cloud scan engine unavailable on this server</AlertTitle>
          <AlertDescription>
            The scanner binary isn&apos;t resolvable at SCANNER_BINARY_PATH — every cloud scan will
            fail until this is fixed and the backend is restarted. This is separate from the binary
            checklist below, which covers what&apos;s published for external CI/local download.
          </AlertDescription>
        </Alert>
      )}

      <div>
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">Binary checklist</h2>
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load scanner status."
          isEmpty={false}
          emptyState={<EmptyState title="No data" />}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>OS / Arch</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Version</TableHead>
                <TableHead>Uploaded</TableHead>
                <TableHead>Uploaded by</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.binaries.map((b) => (
                <TableRow key={`${b.os}-${b.arch}`}>
                  <TableCell className="font-mono text-xs">
                    {b.os}-{b.arch}
                  </TableCell>
                  <TableCell>
                    {b.published ? (
                      <Badge variant="secondary">
                        <CheckCircle2 /> Published
                      </Badge>
                    ) : (
                      <Badge variant="destructive">
                        <XCircle /> Missing
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{b.version ?? "—"}</TableCell>
                  <TableCell className="text-xs">{formatDate(b.uploaded_at)}</TableCell>
                  <TableCell className="font-mono text-xs">{b.uploaded_by ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">Cloud scan queue</h2>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <StatCard label="Running" value={data?.queue.running ?? "—"} isLoading={isLoading} />
          <StatCard label="Queued" value={data?.queue.queued ?? "—"} isLoading={isLoading} />
          <StatCard
            label="Concurrency slots"
            value={data ? `${data.queue.running} / ${data.queue.max_concurrent}` : "—"}
            isLoading={isLoading}
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
              <TableRow>
                <TableHead>Scan</TableHead>
                <TableHead>Project</TableHead>
                <TableHead>Started</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.queue.running_scans.map((s) => (
                <TableRow key={s.scan_id}>
                  <TableCell className="font-mono text-xs">{s.scan_id}</TableCell>
                  <TableCell className="font-mono text-xs">{s.project_id}</TableCell>
                  <TableCell className="text-xs">{formatDate(s.started_at)}</TableCell>
                  <TableCell>
                    {s.stuck && <Badge variant="destructive">Stuck — pending reap</Badge>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>

      <div>
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">Recent failures</h2>
        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load recent failures."
          isEmpty={!!data && data.recent_failures.length === 0}
          emptyState={<EmptyState title="No recent scan failures." />}
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Error</TableHead>
                <TableHead>When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data?.recent_failures.map((f) => (
                <TableRow key={f.scan_id}>
                  <TableCell className="font-mono text-xs">{f.project_id}</TableCell>
                  <TableCell className="text-xs uppercase">{f.scan_type}</TableCell>
                  <TableCell className="max-w-md truncate text-xs" title={f.error_message ?? undefined}>
                    {f.error_message ?? "—"}
                  </TableCell>
                  <TableCell className="text-xs">{formatDate(f.completed_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>
    </div>
  );
}

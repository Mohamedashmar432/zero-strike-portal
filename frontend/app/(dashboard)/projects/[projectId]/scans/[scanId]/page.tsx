"use client";

import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listFindings, type FindingKind, type Severity } from "@/lib/api/findings";
import { getProject } from "@/lib/api/projects";
import { downloadReportPdf, getReport } from "@/lib/api/reports";
import { getScan } from "@/lib/api/scans";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const KINDS: FindingKind[] = ["sast", "secret", "sca", "config"];

function fileLine(file: string, line: number | null) {
  return line ? `${file}:${line}` : file;
}

export default function ScanDetailPage() {
  const { projectId, scanId } = useParams<{ projectId: string; scanId: string }>();
  const [severity, setSeverity] = useState<Severity>();
  const [kind, setKind] = useState<FindingKind>();
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  async function handleDownloadPdf() {
    setDownloadingPdf(true);
    try {
      const blob = await downloadReportPdf(scanId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `scan-${scanId}-report.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Failed to download PDF report");
    } finally {
      setDownloadingPdf(false);
    }
  }

  const { data: project } = useQuery({
    queryKey: ["projects", projectId],
    queryFn: () => getProject(projectId),
  });

  const { data: scan, isLoading: scanLoading } = useQuery({
    queryKey: ["scans", scanId],
    queryFn: () => getScan(scanId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "pending" || s === "running" ? 3000 : false;
    },
  });

  const completed = scan?.status === "completed";

  const { data: report } = useQuery({
    queryKey: ["scans", scanId, "report"],
    queryFn: () => getReport(scanId),
    enabled: completed,
    retry: false,
  });

  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ["scans", scanId, "findings", severity ?? "", kind ?? ""],
    queryFn: () => listFindings(scanId, { severity, kind }),
    enabled: completed,
    retry: false,
  });

  if (scanLoading || !scan) {
    return <Skeleton className="h-40 w-full" />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Breadcrumbs
          items={[
            { label: "Projects", href: "/projects" },
            { label: project?.name ?? projectId, href: `/projects/${projectId}?tab=scans` },
            { label: scan.scan_label || "Scan" },
          ]}
        />
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{scan.scan_label || "Scan"}</h1>
          <ScanTypeBadge scanType={scan.scan_type} />
          <ScanStatusBadge status={scan.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          Created {new Date(scan.created_at).toLocaleString()}
          {scan.repo_url ? ` · ${scan.repo_url}` : ""}
          {scan.branch ? ` (${scan.branch})` : ""}
        </p>
      </div>

      {scan.status === "failed" && (
        <Alert variant="destructive">
          <AlertTitle>Scan failed</AlertTitle>
          <AlertDescription>{scan.error_message || "Scan failed."}</AlertDescription>
        </Alert>
      )}

      {!completed && scan.status !== "failed" && (
        <Alert>
          <AlertTitle>{scan.status === "running" ? "Scan in progress" : "Waiting for the scanner"}</AlertTitle>
          <AlertDescription>
            {scan.status === "running"
              ? "The scan is running on the server. This page updates automatically — no need to refresh."
              : "Waiting for the scanner to report…"}
          </AlertDescription>
        </Alert>
      )}

      {completed && (
        <>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0">
              <CardTitle>Summary</CardTitle>
              <Button size="sm" variant="outline" disabled={downloadingPdf} onClick={handleDownloadPdf}>
                {downloadingPdf ? "Preparing…" : "Download PDF"}
              </Button>
            </CardHeader>
            <CardContent className="space-y-3">
              <dl className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
                <div>
                  <dt className="text-muted-foreground">Findings</dt>
                  <dd className="font-mono text-lg">{report?.stats.total_findings ?? findings?.total ?? 0}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Files scanned</dt>
                  <dd className="font-mono text-lg">{report?.stats.files_scanned ?? "—"}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Duration</dt>
                  <dd className="font-mono text-lg">
                    {report?.duration_ms != null ? `${(report.duration_ms / 1000).toFixed(1)}s` : "—"}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Scanner</dt>
                  <dd className="font-mono text-sm">{report?.scanner_version ?? scan.scanner_version ?? "—"}</dd>
                </div>
              </dl>
              {report && Object.keys(report.stats.by_severity).length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {SEVERITIES.filter((s) => report.stats.by_severity[s]).map((s) => (
                    <span key={s} className="flex items-center gap-1 text-xs">
                      <SeverityBadge severity={s} />
                      <span className="font-mono">{report.stats.by_severity[s]}</span>
                    </span>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm text-muted-foreground">Filter:</span>
            {SEVERITIES.map((s) => (
              <Button
                key={s}
                size="xs"
                variant={severity === s ? "secondary" : "ghost"}
                onClick={() => setSeverity(severity === s ? undefined : s)}
              >
                {s}
              </Button>
            ))}
            <span className="mx-1 text-muted-foreground">·</span>
            {KINDS.map((k) => (
              <Button
                key={k}
                size="xs"
                variant={kind === k ? "secondary" : "ghost"}
                onClick={() => setKind(kind === k ? undefined : k)}
              >
                {k}
              </Button>
            ))}
          </div>

          <DataTableCard
            isLoading={findingsLoading}
            isError={false}
            isEmpty={!!findings && findings.items.length === 0}
            emptyState={
              <EmptyState
                title={`No findings${severity || kind ? " match this filter" : ""}.`}
              />
            }
          >
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Severity</TableHead>
                  <TableHead>Rule</TableHead>
                  <TableHead>Message</TableHead>
                  <TableHead>Location</TableHead>
                  <TableHead>Kind</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {findings?.items.map((f) => (
                  <TableRow key={f.id}>
                    <TableCell>{f.severity && <SeverityBadge severity={f.severity} />}</TableCell>
                    <TableCell className="font-mono text-xs">{f.rule_id ?? "—"}</TableCell>
                    <TableCell className="max-w-md truncate" title={f.message}>
                      {f.message}
                    </TableCell>
                    <TableCell
                      className="max-w-xs truncate font-mono text-xs"
                      title={fileLine(f.location.file, f.location.start_line)}
                    >
                      {fileLine(f.location.file, f.location.start_line)}
                    </TableCell>
                    <TableCell>
                      {f.kind && (
                        <Badge variant="secondary" className="font-mono uppercase">
                          {f.kind}
                        </Badge>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </DataTableCard>
          {findings && findings.total > findings.items.length && (
            <p className="text-center text-xs text-muted-foreground">
              Showing {findings.items.length} of {findings.total} findings.
            </p>
          )}
        </>
      )}
    </div>
  );
}

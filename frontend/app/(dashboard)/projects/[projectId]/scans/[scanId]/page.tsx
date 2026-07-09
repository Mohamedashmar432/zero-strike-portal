"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listFindings, type FindingKind, type Severity } from "@/lib/api/findings";
import { downloadReport, getReport } from "@/lib/api/reports";
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

  async function handleDownload(fmt: "json" | "html") {
    try {
      const blob = await downloadReport(scanId, fmt);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `report.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Download failed");
    }
  }

  if (scanLoading || !scan) {
    return <Skeleton className="h-40 w-full" />;
  }

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <Link
          href={`/projects/${projectId}?tab=scans`}
          className="text-sm text-muted-foreground underline-offset-4 hover:underline"
        >
          ← Back to scans
        </Link>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold">{scan.scan_label || "Scan"}</h1>
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
        <Card className="border-severity-critical/40">
          <CardContent className="pt-4 text-sm text-severity-critical">
            {scan.error_message || "Scan failed."}
          </CardContent>
        </Card>
      )}

      {!completed && scan.status !== "failed" && (
        <Card>
          <CardContent className="p-8 text-center text-sm text-muted-foreground">
            {scan.status === "running" ? "Scan in progress…" : "Waiting for the scanner to report…"}
          </CardContent>
        </Card>
      )}

      {completed && (
        <>
          <Card>
            <CardHeader className="flex-row items-center justify-between">
              <CardTitle>Summary</CardTitle>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => handleDownload("json")}>
                  Download JSON
                </Button>
                {report?.html_available && (
                  <Button size="sm" variant="outline" onClick={() => handleDownload("html")}>
                    Download HTML
                  </Button>
                )}
              </div>
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

          <Card>
            <CardContent className="p-0">
              {findingsLoading ? (
                <div className="space-y-2 p-4">
                  <Skeleton className="h-8 w-full" />
                </div>
              ) : findings && findings.items.length === 0 ? (
                <div className="p-10 text-center text-sm text-muted-foreground">
                  No findings{severity || kind ? " match this filter" : ""}.
                </div>
              ) : (
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
                        <TableCell className="max-w-md">{f.message}</TableCell>
                        <TableCell className="font-mono text-xs">{fileLine(f.location.file, f.location.start_line)}</TableCell>
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
              )}
            </CardContent>
          </Card>
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

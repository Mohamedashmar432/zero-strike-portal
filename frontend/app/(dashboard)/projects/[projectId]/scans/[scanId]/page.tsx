"use client";

import { useQueries, useQuery } from "@tanstack/react-query";
import { ChevronRight, Download, Search, Sparkles, Wand2 } from "lucide-react";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { listFindings, type Finding, type FindingKind, type Severity } from "@/lib/api/findings";
import { getProject } from "@/lib/api/projects";
import { downloadReportPdf, getReport } from "@/lib/api/reports";
import { getScan, listScans } from "@/lib/api/scans";

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const KINDS: FindingKind[] = ["sast", "secret", "sca", "config"];

// Not a real CVSS score — a conventional severity-tier approximation, shown so the
// findings list has the "score" column the design calls for without fabricating
// false precision.
const SEVERITY_SCORE: Record<Severity, number> = { critical: 9.5, high: 7.5, medium: 5, low: 2.5, info: 1 };
const SEVERITY_SCORE_CLASS: Record<Severity, string> = {
  critical: "text-severity-critical",
  high: "text-severity-high",
  medium: "text-severity-medium",
  low: "text-severity-low",
  info: "text-severity-info",
};

const trendChartConfig: ChartConfig = {
  total: { label: "Findings", color: "var(--primary)" },
};

function fileLine(file: string, line: number | null) {
  return line ? `${file}:${line}` : file;
}

// No AI provider is configured anywhere in this app yet (see Settings > AI Provider /
// Auto-fix) — these buttons stay visible per the design, but honestly say so instead
// of pretending to call a model that doesn't exist.
function notifyComingSoon(feature: string) {
  toast.info(`${feature} isn't available yet`, {
    description: "Configure an AI provider in Settings → AI Provider to enable this.",
  });
}

function timeAgo(dateStr: string) {
  const diffMs = Date.now() - new Date(dateStr).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} minute${mins === 1 ? "" : "s"} ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
}

function FindingItem({
  finding,
  expanded,
  onToggle,
}: {
  finding: Finding;
  expanded: boolean;
  onToggle: () => void;
}) {
  const snippet = finding.evidence[0]?.snippet;
  return (
    <div className="overflow-hidden rounded-xl border border-border">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center gap-4 p-4 text-left hover:bg-accent/40"
      >
        <ChevronRight
          className={cn("size-4 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-90")}
        />
        {finding.severity && <SeverityBadge severity={finding.severity} />}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{finding.rule_name || finding.rule_id || "Finding"}</p>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {fileLine(finding.location.file, finding.location.start_line)}
          </p>
        </div>
        <div className="hidden shrink-0 gap-6 text-right text-xs md:flex">
          <div>
            <p className="text-muted-foreground">Category</p>
            <p className="font-medium">{finding.category ?? "—"}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Score</p>
            <p className={cn("font-mono font-bold", finding.severity && SEVERITY_SCORE_CLASS[finding.severity])}>
              {finding.severity ? SEVERITY_SCORE[finding.severity].toFixed(1) : "—"}
            </p>
          </div>
        </div>
      </button>
      {expanded && (
        <div className="grid grid-cols-1 border-t border-border lg:grid-cols-12">
          <div className="overflow-x-auto bg-[#1e1c1b] p-4 text-[#d4ccc8] lg:col-span-8">
            {snippet ? (
              <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap">{snippet}</pre>
            ) : (
              <p className="text-xs text-muted-foreground">No code snippet available for this finding.</p>
            )}
          </div>
          <div className="space-y-4 border-t border-border bg-muted/30 p-4 lg:col-span-4 lg:border-t-0 lg:border-l">
            <div>
              <h6 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                Vulnerability Details
              </h6>
              {finding.cwe.length > 0 && (
                <p className="mt-1 font-mono text-xs text-muted-foreground">{finding.cwe.join(", ")}</p>
              )}
              <p className="mt-1 text-sm">{finding.rationale || finding.message}</p>
            </div>
            {finding.remediation && (
              <div>
                <h6 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                  Recommendation
                </h6>
                <pre className="mt-1 rounded-lg bg-primary/10 p-2 font-mono text-xs whitespace-pre-wrap text-primary">
                  {finding.remediation}
                </pre>
              </div>
            )}
            <div className="flex flex-col gap-2 border-t border-border pt-4">
              <Button variant="outline" size="sm" onClick={() => notifyComingSoon("AI analysis")}>
                <Sparkles />
                Analyze with AI
              </Button>
              <Button size="sm" onClick={() => notifyComingSoon("Auto-fix")}>
                <Wand2 />
                Apply Auto-Fix
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function ScanDetailPage() {
  const { projectId, scanId } = useParams<{ projectId: string; scanId: string }>();
  const [severity, setSeverity] = useState<Severity>();
  const [kind, setKind] = useState<FindingKind>();
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [downloadingPdf, setDownloadingPdf] = useState(false);

  function toggleExpanded(id: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

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

  // Unfiltered/uncapped-ish fetch used only to build the Risk Profile below — kept
  // separate from the (severity/kind-filtered, paginated) query that feeds the list.
  const { data: allFindings } = useQuery({
    queryKey: ["scans", scanId, "findings", "risk-profile"],
    queryFn: () => listFindings(scanId, { pageSize: 200 }),
    enabled: completed,
    retry: false,
  });

  const { data: recentScans } = useQuery({
    queryKey: ["projects", projectId, "scans", "trend"],
    queryFn: () => listScans(projectId, 1, 6),
  });

  const trendReportQueries = useQueries({
    queries: (recentScans?.items ?? []).map((s) => ({
      queryKey: ["scans", s.id, "report"],
      queryFn: () => getReport(s.id),
      enabled: s.status === "completed",
      retry: false,
    })),
  });

  const trendData = useMemo(() => {
    const scans = recentScans?.items ?? [];
    return scans
      .map((s, i) => ({
        label: s.scan_label || new Date(s.created_at).toLocaleDateString(undefined, { month: "numeric", day: "numeric" }),
        total: trendReportQueries[i]?.data?.stats.total_findings ?? 0,
      }))
      .reverse();
  }, [recentScans, trendReportQueries]);

  // Grouped by each finding's real OWASP tags where the scanner populated them;
  // falls back to the report's general category breakdown (counts only, so the
  // bar height there is a rough visual scale, not a severity-weighted score).
  const riskProfile = useMemo(() => {
    const items = allFindings?.items ?? [];
    const byTag = new Map<string, number[]>();
    for (const f of items) {
      const weight = f.severity ? SEVERITY_SCORE[f.severity] : 0;
      for (const tag of f.owasp) {
        if (!byTag.has(tag)) byTag.set(tag, []);
        byTag.get(tag)!.push(weight);
      }
    }
    let rows = Array.from(byTag.entries()).map(([label, weights]) => ({
      label,
      score: weights.reduce((a, b) => a + b, 0) / weights.length,
    }));
    if (rows.length === 0 && report) {
      rows = Object.entries(report.stats.by_category).map(([label, count]) => ({
        label,
        score: Math.min(10, count * 2),
      }));
    }
    return rows.sort((a, b) => b.score - a.score).slice(0, 4);
  }, [allFindings, report]);

  const visibleFindings = useMemo(() => {
    const items = findings?.items ?? [];
    if (!search) return items;
    const q = search.toLowerCase();
    return items.filter(
      (f) => f.message.toLowerCase().includes(q) || (f.rule_id ?? "").toLowerCase().includes(q)
    );
  }, [findings, search]);

  if (scanLoading || !scan) {
    return <Skeleton className="h-40 w-full" />;
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
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
        {completed && (
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" disabled={downloadingPdf} onClick={handleDownloadPdf}>
              <Download />
              {downloadingPdf ? "Preparing…" : "Generate Report"}
            </Button>
            <Button variant="outline" onClick={() => notifyComingSoon("AI Analysis")}>
              <Sparkles />
              AI Analysis
            </Button>
            <Button onClick={() => notifyComingSoon("Auto AI Fix")}>
              <Wand2 />
              Auto AI Fix
            </Button>
          </div>
        )}
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
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            {[
              { label: "Total Findings", value: report?.stats.total_findings ?? findings?.total ?? 0 },
              {
                label: "Critical Unresolved",
                value: report?.stats.by_severity.critical ?? 0,
                valueClassName: "text-severity-critical",
              },
              { label: "Files Scanned", value: report?.stats.files_scanned ?? "—" },
              {
                label: "Duration",
                value: report?.duration_ms != null ? `${(report.duration_ms / 1000).toFixed(1)}s` : "—",
              },
            ].map((stat) => (
              <Card key={stat.label}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
                    {stat.label}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <span className={cn("text-2xl font-semibold tracking-tight", stat.valueClassName)}>
                    {stat.value}
                  </span>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <Card className="lg:col-span-2">
              <CardHeader>
                <CardTitle className="text-sm font-normal text-muted-foreground">Scan Trend</CardTitle>
              </CardHeader>
              <CardContent>
                {trendData.every((d) => d.total === 0) && trendData.length <= 1 ? (
                  <EmptyState title="Not enough scan history yet" description="Run more scans to see a trend." />
                ) : (
                  <ChartContainer config={trendChartConfig} className="h-[220px] w-full">
                    <BarChart data={trendData}>
                      <CartesianGrid vertical={false} strokeDasharray="3 3" />
                      <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={12} />
                      <ChartTooltip content={<ChartTooltipContent />} />
                      <Bar dataKey="total" fill="var(--color-total)" radius={4} />
                    </BarChart>
                  </ChartContainer>
                )}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-normal text-muted-foreground">Risk Profile</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {riskProfile.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No categorized findings for this scan.</p>
                ) : (
                  riskProfile.map((row) => (
                    <div key={row.label} className="space-y-1">
                      <div className="flex justify-between text-sm">
                        <span className="truncate">{row.label}</span>
                        <span className="font-semibold">{row.score.toFixed(1)}</span>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-sm bg-muted">
                        <div
                          className={cn(
                            "h-full",
                            row.score >= 8 ? "bg-severity-critical" : row.score >= 5 ? "bg-severity-high" : "bg-severity-medium"
                          )}
                          style={{ width: `${Math.min(100, (row.score / 10) * 100)}%` }}
                        />
                      </div>
                    </div>
                  ))
                )}
              </CardContent>
            </Card>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
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
            <div className="relative w-full sm:w-64">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search findings…"
                className="pl-8"
              />
            </div>
          </div>

          <DataTableCard
            bare
            isLoading={findingsLoading}
            isError={false}
            isEmpty={!!findings && visibleFindings.length === 0}
            emptyState={
              <EmptyState title={`No findings${severity || kind || search ? " match this filter" : ""}.`} />
            }
          >
            <div className="space-y-2">
              {visibleFindings.map((f) => (
                <FindingItem key={f.id} finding={f} expanded={expanded.has(f.id)} onToggle={() => toggleExpanded(f.id)} />
              ))}
            </div>
          </DataTableCard>
          {findings && findings.total > findings.items.length && (
            <p className="text-center text-xs text-muted-foreground">
              Showing {findings.items.length} of {findings.total} findings.
            </p>
          )}
          <footer className="border-t border-border pt-6 text-center text-xs text-muted-foreground">
            ZeroStrike Security Platform Scan Engine
            {report?.scanner_version || scan.scanner_version ? ` v${report?.scanner_version ?? scan.scanner_version}` : ""}
            {" · "}
            Last scan completed {timeAgo(scan.completed_at ?? scan.created_at)}.
          </footer>
        </>
      )}
    </div>
  );
}

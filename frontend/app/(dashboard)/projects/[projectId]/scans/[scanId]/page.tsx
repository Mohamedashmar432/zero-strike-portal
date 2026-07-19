"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Download, Loader2, RefreshCw, Sparkles, Wand2 } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { ScanStatusBadge } from "@/components/scans/scan-status-badge";
import { ScanTypeBadge } from "@/components/scans/scan-type-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { CodeSnippet } from "@/components/findings/code-snippet";
import { OwaspChart } from "@/components/common/owasp-chart";
import { FilterBar } from "@/components/common/filter-bar";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { StatCard } from "@/components/common/stat-card";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { owaspChartData, OWASP_TITLES } from "@/lib/owasp";
import { PRIORITY_TIERS, PRIORITY_LABELS, PRIORITY_CLASS, type PriorityTier } from "@/lib/priority";
import {
  getAiStatus,
  getFindingAnalysis,
  getScanAnalysis,
  triggerFindingAnalysis,
  triggerScanAnalysis,
  type AiAnalysisResult,
  type FindingInsight,
  type ScanInsight,
} from "@/lib/api/ai";
import { listFindings, type Finding, type FindingKind, type Severity } from "@/lib/api/findings";
import { refetchWhileStatusActive } from "@/lib/api/polling";
import { getProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import { downloadReportPdf, getReport } from "@/lib/api/reports";
import { createCloudScan, getScan, type Scan } from "@/lib/api/scans";

// Client-side verdict derivation -- the backend has no separate `verdict` enum, only
// is_false_positive/false_positive_confidence (see docs/ARCHITECTURE_REVIEW_AND_AI_ROADMAP.md).
function findingVerdict(insight: FindingInsight | null | undefined): {
  label: string;
  variant: "secondary" | "destructive" | "outline";
} | null {
  if (!insight) return null;
  if (insight.is_false_positive === true) return { label: "Possible false positive", variant: "secondary" };
  if (insight.is_false_positive === false) return { label: "Likely valid", variant: "destructive" };
  return { label: "Needs review", variant: "outline" };
}

const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const KINDS: FindingKind[] = ["sast", "secret", "sca", "config"];
const ALL = "__all__";

function fileLine(file: string, line: number | null) {
  return line ? `${file}:${line}` : file;
}

// Auto-fix (fix proposals / diff viewer) isn't built yet (see Settings > Auto-fix) — these
// buttons stay visible per the design, but honestly say so instead of pretending to call
// a model that doesn't exist. AI *analysis* (the other button in each pair) is wired for
// real below.
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

// Re-scanning a manual (non-connected) repo needs the token re-entered — the original
// token is transient and cleared once the scan is claimed, never persisted anywhere.
function RescanDialog({
  projectId,
  scan,
  open,
  onClose,
}: {
  projectId: string;
  scan: Scan;
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [token, setToken] = useState("");

  const rescan = useMutation({
    mutationFn: () =>
      createCloudScan(projectId, {
        repo_url: scan.repo_url ?? undefined,
        branch: scan.branch ?? undefined,
        repo_token: token || undefined,
        scan_label: scan.scan_label ?? undefined,
      }),
    onSuccess: (createdScan) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.scans(projectId) });
      toast.success("Re-scan started");
      onClose();
      router.push(`/projects/${projectId}/scans/${createdScan.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to start re-scan"),
  });

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Re-scan repository</DialogTitle>
          <DialogDescription>
            Re-clones <code>{scan.repo_url}</code>
            {scan.branch ? ` (${scan.branch})` : ""} and scans it again. Provide an access token if this is a
            private repo — the original token wasn&apos;t saved.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2 py-2">
          <Label htmlFor="rescan-token">Access token (private repos only)</Label>
          <Input
            id="rescan-token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={rescan.isPending} onClick={() => rescan.mutate()}>
            {rescan.isPending ? "Starting…" : "Start re-scan"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Exported (rather than kept file-private) solely so it has a stable import path for its
// own test file -- it still has exactly one real call site, below in ScanDetailPage.
export function FindingItem({
  finding,
  expanded,
  onToggle,
  aiEnabled,
}: {
  finding: Finding;
  expanded: boolean;
  onToggle: () => void;
  /** From the page-level GET /ai/status query -- whether an AI provider is configured at all. */
  aiEnabled: boolean;
}) {
  const snippet = finding.evidence[0]?.snippet;
  const queryClient = useQueryClient();
  const canAnalyze = aiEnabled && finding.fingerprint != null;

  const { data: analysis } = useQuery({
    queryKey: queryKeys.ai.findingInsight(finding.id),
    queryFn: () => getFindingAnalysis(finding.id),
    enabled: expanded && canAnalyze,
    refetchInterval: refetchWhileStatusActive<AiAnalysisResult<FindingInsight>>(),
  });

  const trigger = useMutation({
    mutationFn: (opts: { force?: boolean }) => triggerFindingAnalysis(finding.id, opts),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.ai.findingInsight(finding.id), result);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to start AI analysis"),
  });

  const status = analysis?.status ?? "not_requested";
  const isAnalyzing = trigger.isPending || status === "queued" || status === "in_progress";
  // Once there's a terminal result, the top trigger button is replaced by the Re-analyze/
  // Retry button living inside the result subsection below -- but it stays visible (showing
  // a spinner) while a request is in flight, per the loading state in the spec.
  const hideTriggerButton = status === "completed" || status === "failed";
  const showResultSection = isAnalyzing || hideTriggerButton;
  const verdict = findingVerdict(analysis?.insight);
  // Display-only AI severity overlay: only when the AI actually differs from the scanner.
  const adjustedSeverity =
    analysis?.insight?.adjusted_severity && analysis.insight.adjusted_severity !== finding.severity
      ? analysis.insight.adjusted_severity
      : null;
  const hint = !aiEnabled
    ? "Configure an AI provider in Settings → AI Provider to enable this."
    : !canAnalyze
      ? "AI analysis isn't available for this finding."
      : undefined;

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
        {adjustedSeverity && (
          <span
            className="inline-flex items-center gap-1 text-xs text-muted-foreground"
            title={analysis?.insight?.severity_reasoning || "AI-adjusted severity"}
          >
            <span className="font-mono font-semibold">AI→</span>
            <SeverityBadge severity={adjustedSeverity} />
          </span>
        )}
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
            <p className="text-muted-foreground">Priority</p>
            <p className={cn("font-mono font-bold", finding.priority_tier && PRIORITY_CLASS[finding.priority_tier])}>
              {finding.priority_score != null ? finding.priority_score.toFixed(1) : "—"}
              {finding.priority_tier ? ` (${PRIORITY_LABELS[finding.priority_tier]})` : ""}
            </p>
          </div>
        </div>
      </button>
      {expanded && (
        <div className={cn("grid grid-cols-1 border-t border-border", snippet && "lg:grid-cols-12")}>
          {snippet && (
            <div className="lg:col-span-8">
              <CodeSnippet
                snippet={snippet}
                snippetStartLine={finding.evidence[0]?.start_line ?? null}
                highlightStart={finding.location.start_line}
                highlightEnd={finding.location.end_line ?? finding.location.start_line}
              />
            </div>
          )}
          <div
            className={cn(
              "space-y-4 border-t border-border bg-muted/30 p-4 lg:border-t-0",
              snippet ? "lg:col-span-4 lg:border-l" : ""
            )}
          >
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
              {!hideTriggerButton && (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!canAnalyze || isAnalyzing}
                  title={hint}
                  onClick={() => trigger.mutate({ force: false })}
                >
                  {isAnalyzing ? <Loader2 className="animate-spin" /> : <Sparkles />}
                  {isAnalyzing ? "Analyzing…" : "Analyze with AI"}
                </Button>
              )}
              <Button size="sm" onClick={() => notifyComingSoon("Auto-fix")}>
                <Wand2 />
                Apply Auto-Fix
              </Button>
            </div>
            {/* Deliberately a separate, visually distinct block from Vulnerability Details/
                Recommendation above -- a security tool's raw scanner output must stay separable
                from AI-generated content. */}
            {showResultSection && (
              <div className="space-y-2 border-t border-border pt-4">
                <h6 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                  AI Analysis
                </h6>
                {isAnalyzing && (
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-1/3" />
                    <Skeleton className="h-16 w-full" />
                  </div>
                )}
                {status === "completed" && analysis?.insight && (
                  <div className="space-y-2 rounded-lg border border-border bg-background p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      {verdict && <Badge variant={verdict.variant}>{verdict.label}</Badge>}
                      {analysis.insight.false_positive_confidence != null && (
                        <span className="text-xs text-muted-foreground">
                          {Math.round(analysis.insight.false_positive_confidence * 100)}% confidence
                        </span>
                      )}
                    </div>
                    {analysis.insight.adjusted_severity &&
                      analysis.insight.adjusted_severity !== finding.severity && (
                        <p className="text-sm">
                          <span className="font-medium">AI severity: </span>
                          <span className="uppercase">{finding.severity ?? "—"}</span>
                          {" → "}
                          <span className="font-semibold uppercase">{analysis.insight.adjusted_severity}</span>
                          {analysis.insight.severity_reasoning ? ` — ${analysis.insight.severity_reasoning}` : ""}
                        </p>
                      )}
                    {analysis.insight.explanation && <p className="text-sm">{analysis.insight.explanation}</p>}
                    {analysis.insight.improved_description && (
                      <p className="text-sm text-muted-foreground">{analysis.insight.improved_description}</p>
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={trigger.isPending}
                      onClick={() => trigger.mutate({ force: true })}
                    >
                      <RefreshCw />
                      Re-analyze
                    </Button>
                  </div>
                )}
                {status === "failed" && (
                  <>
                    <Alert variant="destructive">
                      <AlertTitle>AI analysis failed</AlertTitle>
                      <AlertDescription>{analysis?.error_message || "Something went wrong."}</AlertDescription>
                    </Alert>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={trigger.isPending}
                      onClick={() => trigger.mutate({ force: false })}
                    >
                      Retry
                    </Button>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ScanDetailPage() {
  const { projectId, scanId } = useParams<{ projectId: string; scanId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [severity, setSeverity] = useState<Severity>();
  const [kind, setKind] = useState<FindingKind>();
  const [owaspFilter, setOwaspFilter] = useState<string>();
  const [priority, setPriority] = useState<PriorityTier>();
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [rescanDialogOpen, setRescanDialogOpen] = useState(false);

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
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });

  const { data: scan, isLoading: scanLoading } = useQuery({
    queryKey: queryKeys.scans.detail(scanId),
    queryFn: () => getScan(scanId),
    refetchInterval: refetchWhileStatusActive<Scan>(),
  });

  // Direct one-click re-scan when the scan came from a connected repo (credential is
  // stored, nothing to re-enter). Manual repo_url scans go through RescanDialog instead,
  // since their token is transient and was never persisted.
  const rescan = useMutation({
    mutationFn: () =>
      createCloudScan(projectId, { project_repo_id: scan!.project_repo_id!, scan_label: scan!.scan_label ?? undefined }),
    onSuccess: (createdScan) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.scans(projectId) });
      toast.success("Re-scan started");
      router.push(`/projects/${projectId}/scans/${createdScan.id}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to start re-scan"),
  });

  const completed = scan?.status === "completed";

  const { data: report } = useQuery({
    queryKey: queryKeys.scans.report(scanId),
    queryFn: () => getReport(scanId),
    enabled: completed,
    retry: false,
  });

  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: queryKeys.scans.findings(scanId, {
      severity,
      kind,
      owasp: owaspFilter,
      priority,
    }),
    queryFn: () => listFindings(scanId, { severity, kind, owasp: owaspFilter, priority }),
    enabled: completed,
    retry: false,
  });

  const { data: aiStatus } = useQuery({
    queryKey: queryKeys.ai.status(),
    queryFn: getAiStatus,
  });
  const aiEnabled = aiStatus?.enabled ?? false;

  const { data: scanAnalysis } = useQuery({
    queryKey: queryKeys.ai.scanInsight(scanId),
    queryFn: () => getScanAnalysis(scanId),
    enabled: completed,
    refetchInterval: refetchWhileStatusActive<AiAnalysisResult<ScanInsight>>(),
    retry: false,
  });

  const triggerScan = useMutation({
    mutationFn: (opts: { force?: boolean }) => triggerScanAnalysis(scanId, opts),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.ai.scanInsight(scanId), result);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to start AI analysis"),
  });
  const scanAnalysisStatus = scanAnalysis?.status ?? "not_requested";
  const scanAnalysisLoading =
    triggerScan.isPending || scanAnalysisStatus === "queued" || scanAnalysisStatus === "in_progress";

  const owaspData = useMemo(() => owaspChartData(report?.stats.by_owasp), [report]);

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
            <AiStatusBadge
              status={scanAnalysis?.status}
              startedAt={scanAnalysis?.started_at}
              progressCompleted={scanAnalysis?.progress_completed}
              progressTotal={scanAnalysis?.progress_total}
            />
          </div>
          <p className="text-sm text-muted-foreground">
            Created {new Date(scan.created_at).toLocaleString()}
            {scan.repo_url ? ` · ${scan.repo_url}` : ""}
            {scan.branch ? ` (${scan.branch})` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {scan.scan_type === "cloud" && (scan.project_repo_id || scan.repo_url) && (
            <Button
              variant="outline"
              disabled={rescan.isPending}
              onClick={() => (scan.project_repo_id ? rescan.mutate() : setRescanDialogOpen(true))}
            >
              <RefreshCw />
              {rescan.isPending ? "Starting…" : "Re-scan"}
            </Button>
          )}
          {completed && (
            <>
              <Button variant="outline" disabled={downloadingPdf} onClick={handleDownloadPdf}>
                <Download />
                {downloadingPdf ? "Preparing…" : "Generate Report"}
              </Button>
              <Button
                variant="outline"
                disabled={!aiEnabled || scanAnalysisLoading}
                title={!aiEnabled ? "Configure an AI provider in Settings → AI Provider to enable this." : undefined}
                onClick={() => triggerScan.mutate({ force: scanAnalysisStatus !== "not_requested" })}
              >
                {scanAnalysisLoading ? <Loader2 className="animate-spin" /> : <Sparkles />}
                {scanAnalysisLoading ? "Analyzing…" : "AI Analysis"}
              </Button>
              <Button onClick={() => notifyComingSoon("Auto AI Fix")}>
                <Wand2 />
                Auto AI Fix
              </Button>
            </>
          )}
        </div>
      </div>

      {scan.scan_type === "cloud" && scan.repo_url && !scan.project_repo_id && (
        <RescanDialog
          projectId={projectId}
          scan={scan}
          open={rescanDialogOpen}
          onClose={() => setRescanDialogOpen(false)}
        />
      )}

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
              <StatCard key={stat.label} size="sm" {...stat} />
            ))}
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-sm font-normal text-muted-foreground">OWASP Top 10 Compliance</CardTitle>
            </CardHeader>
            <CardContent>
              <OwaspChart data={owaspData} activeCategory={owaspFilter} onSelectCategory={(code) =>
                setOwaspFilter((prev) => (prev === code ? undefined : code))
              } />
            </CardContent>
          </Card>

          {/* Only rendered once AI analysis has actually been requested for this scan --
              otherwise this page looks exactly as it does today. */}
          {scanAnalysis && scanAnalysisStatus !== "not_requested" && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm font-normal text-muted-foreground">AI Analysis</CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {scanAnalysisLoading && (
                  <Alert>
                    <AlertTitle>Analyzing findings…</AlertTitle>
                    <AlertDescription>
                      This runs in the background — this page updates automatically.
                    </AlertDescription>
                  </Alert>
                )}
                {scanAnalysisStatus === "completed" && scanAnalysis.insight && (
                  <>
                    <Alert>
                      <AlertTitle>Summary</AlertTitle>
                      <AlertDescription>{scanAnalysis.insight.summary || "No summary available."}</AlertDescription>
                    </Alert>
                    <div className="grid grid-cols-2 gap-4 md:grid-cols-3">
                      <StatCard
                        size="sm"
                        label="Findings Analyzed"
                        value={scanAnalysis.insight.total_findings_analyzed ?? "—"}
                      />
                      <StatCard
                        size="sm"
                        label="Possible False Positives"
                        value={scanAnalysis.insight.false_positive_count ?? "—"}
                      />
                    </div>
                    {scanAnalysis.insight.top_recommendations.length > 0 && (
                      <div>
                        <h6 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                          Top Recommendations
                        </h6>
                        <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
                          {scanAnalysis.insight.top_recommendations.map((rec, i) => (
                            <li key={i}>{rec}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </>
                )}
                {scanAnalysisStatus === "failed" && (
                  <>
                    <Alert variant="destructive">
                      <AlertTitle>AI analysis failed</AlertTitle>
                      <AlertDescription>{scanAnalysis.error_message || "Something went wrong."}</AlertDescription>
                    </Alert>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={triggerScan.isPending}
                      onClick={() => triggerScan.mutate({ force: false })}
                    >
                      Retry
                    </Button>
                  </>
                )}
              </CardContent>
            </Card>
          )}

          <FilterBar
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search findings…"
            facets={[
              {
                type: "select",
                value: severity ?? ALL,
                onChange: (v) => setSeverity(v === ALL ? undefined : (v as Severity)),
                placeholder: "Severity",
                options: [{ value: ALL, label: "All severities" }, ...SEVERITIES.map((s) => ({ value: s, label: s }))],
              },
              {
                type: "select",
                value: kind ?? ALL,
                onChange: (v) => setKind(v === ALL ? undefined : (v as FindingKind)),
                placeholder: "Kind",
                options: [{ value: ALL, label: "All kinds" }, ...KINDS.map((k) => ({ value: k, label: k }))],
              },
              {
                type: "select",
                value: owaspFilter ?? ALL,
                onChange: (v) => setOwaspFilter(v === ALL ? undefined : v),
                placeholder: "OWASP category",
                options: [
                  { value: ALL, label: "All OWASP categories" },
                  ...Object.entries(OWASP_TITLES).map(([code, title]) => ({ value: code, label: `${code} — ${title}` })),
                ],
              },
              {
                type: "select",
                value: priority ?? ALL,
                onChange: (v) => setPriority(v === ALL ? undefined : (v as PriorityTier)),
                placeholder: "Priority",
                options: [
                  { value: ALL, label: "All priorities" },
                  ...PRIORITY_TIERS.map((p) => ({ value: p, label: PRIORITY_LABELS[p] })),
                ],
              },
            ]}
          />

          <DataTableCard
            bare
            isLoading={findingsLoading}
            isError={false}
            isEmpty={!!findings && visibleFindings.length === 0}
            emptyState={
              <EmptyState
                title={`No findings${severity || kind || owaspFilter || priority || search ? " match this filter" : ""}.`}
              />
            }
          >
            <div className="space-y-2">
              {visibleFindings.map((f) => (
                <FindingItem
                  key={f.id}
                  finding={f}
                  expanded={expanded.has(f.id)}
                  onToggle={() => toggleExpanded(f.id)}
                  aiEnabled={aiEnabled}
                />
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

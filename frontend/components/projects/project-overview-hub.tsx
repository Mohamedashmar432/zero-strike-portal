"use client";

import {
  Activity,
  AlertOctagon,
  ArrowRight,
  Calendar,
  CheckCircle2,
  Code2,
  FolderGit2,
  GitBranch,
  Globe,
  Radio,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Swords,
  Wand2,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/common/empty-state";
import { PreviewNotice } from "@/components/common/preview-notice";
import { MetricStrip } from "@/components/common/metric-strip";
import { SectionRule } from "@/components/layout/section-rule";
import { ProjectRepoBreakdown } from "@/components/projects/project-repo-breakdown";
import { SeverityCountPills } from "@/components/severity/severity-count-pills";
import { SeveritySpectrum } from "@/components/severity/severity-spectrum";
import { Skeleton } from "@/components/ui/skeleton";
import { listProjectAudits } from "@/lib/api/compliance";
import { queryKeys } from "@/lib/api/query-keys";
import { cn, parseApiDate } from "@/lib/utils";
import type { Project, ProjectScanActivity } from "@/lib/api/projects";
import type { ProjectRepo } from "@/lib/api/project-repos";
import type { ProjectAiUsage } from "@/lib/api/ai";
import type { SeverityCounts } from "@/lib/api/dashboard";

/**
 * The DAST panel below is hardcoded mockup data — "api.payments.internal",
 * "24 / 24 Routes", "0 Active Breaches" — and there is no DAST engine or endpoint
 * behind it. The DAST tab it links to is already `hidden` in project-sidebar.tsx,
 * so this panel was the last route into it. Kept behind a flag rather than deleted
 * so the layout survives for whenever a real engine lands.
 * ponytail: a const, not an env var — flip it here when there's something to show.
 */
const SHOW_DAST_PREVIEW = false;

/**
 * Static class map. Tailwind scans source text, so `bg-${tone}-tint` produces no
 * CSS at all — the classes must appear literally somewhere for them to exist.
 */
const COMPLIANCE_TONE = {
  good: {
    edge: "border-l-status-success",
    chip: "bg-status-success-tint text-status-success",
    bar: "bg-status-success",
  },
  warn: {
    edge: "border-l-severity-medium",
    chip: "bg-severity-medium-tint text-severity-medium",
    bar: "bg-severity-medium",
  },
  bad: {
    edge: "border-l-severity-critical",
    chip: "bg-severity-critical-tint text-severity-critical",
    bar: "bg-severity-critical",
  },
} as const;

interface ProjectOverviewHubProps {
  project: Project;
  activity?: ProjectScanActivity;
  repos?: ProjectRepo[];
  aiUsage?: ProjectAiUsage;
  onNavigateTab: (tabId: string) => void;
}

export function ProjectOverviewHub({
  project,
  activity,
  repos = [],
  aiUsage,
  onNavigateTab,
}: ProjectOverviewHubProps) {
  // Newest audit for this project. `listProjectAudits` is already paginated
  // newest-first, so page 1 size 1 is the cheapest way to get "latest".
  const { data: audits, isLoading: auditsLoading } = useQuery({
    queryKey: queryKeys.compliance.projectAudits(project.id),
    queryFn: () => listProjectAudits(project.id, 1, 1),
  });
  const latestAudit = audits?.items?.[0];

  // Only reflects the latest scan report findings
  const latestCounts: SeverityCounts =
    activity?.current_findings ??
    project.findings_by_severity ?? {
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      info: 0,
    };

  const totalFindings =
    activity?.current_findings_total ?? project.total_findings ?? 0;

  // "Connected" means linked to the project, which is `repos`. The old value
  // counted scan-ACTIVITY groups, so a project with 6 linked repos and 1 scanned
  // rendered "1 connected" directly above a list of 6 — the page contradicted
  // itself. `?.` on both hops: a payload without `repos` used to crash the page.
  const connectedCount = repos.length;
  const scannedCount = activity?.repos?.filter((g) => g.repo_id).length ?? 0;

  // Heuristic, NOT a score anyone should quote. Kept because a single directional
  // number is useful at a glance, but it is now labelled as derived rather than
  // presented like a measured compliance figure.
  const healthScore = Math.max(
    15,
    100 -
      latestCounts.critical * 25 -
      latestCounts.high * 10 -
      latestCounts.medium * 3 -
      latestCounts.low * 1
  );

  const atRiskRepos = project.risk_repo_count ?? 0;
  const totalRepos = project.total_repo_count ?? repos.length;

  const metrics = [
    {
      label: "Health Score",
      value: `${healthScore}`,
      hint: "Heuristic from severity counts. Not an audit result.",
      tone:
        healthScore > 80 ? ("signal" as const)
        : healthScore > 50 ? ("medium" as const)
        : ("critical" as const),
    },
    {
      label: "Latest Findings",
      value: totalFindings.toLocaleString(),
      hint: "Unresolved across latest scans",
      meter: <SeveritySpectrum counts={latestCounts} />,
    },
    {
      label: "Repositories",
      value: `${connectedCount}`,
      hint: scannedCount
        ? `${scannedCount} scanned`
        : project.last_scan_at
          ? `Last scan ${parseApiDate(project.last_scan_at).toLocaleDateString()}`
          : "No scans executed yet",
    },
    {
      label: "At-Risk Repos",
      value: `${atRiskRepos} / ${totalRepos}`,
      hint: atRiskRepos ? "Contain critical or high findings" : "No critical or high findings",
      tone: atRiskRepos > 0 ? ("critical" as const) : ("default" as const),
    },
  ];

  return (
    <div className="space-y-6">
      {/* 1. Posture strip. Same divided rack unit as the workspace dashboard
             rather than four floating cards, and the fabricated "88% SOC 2
             Aligned / ISO 27001 - HIPAA - NIST" cell is gone: nothing on this
             page ever called a compliance endpoint, so that number asserted an
             audit result the product had not measured. Replaced with at-risk
             repos, which is real. */}
      <MetricStrip metrics={metrics} />

      {/* 2. SAST Code Scanner — Latest Scan Findings Across All Repositories */}
      <Card className="border-border/80 bg-card/60">
        <CardHeader className="p-4 pb-3 border-b border-border/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex size-7.5 items-center justify-center rounded-lg bg-primary/10 text-primary border border-primary/20">
                <Code2 className="size-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground">
                  SAST Code Scanner — Latest Scan Findings
                </CardTitle>
                <p className="text-[11px] text-muted-foreground">
                  Latest AST source code scan findings across all connected repositories
                </p>
              </div>
            </div>

            <Button
              variant="outline"
              size="xs"
              onClick={() => onNavigateTab("scans")}
              className="gap-1 text-xs font-medium border-border/80 hover:bg-muted"
            >
              <span>View SAST Console</span>
              <ArrowRight className="size-3" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="p-4 space-y-4">
          {/* SAST Stat Highlights */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Total Scans Executed</span>
              <p className="font-mono text-lg font-bold text-foreground mt-0.5">{project.scan_count || 0}</p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Critical Findings</span>
              <p className="font-mono text-lg font-bold text-severity-critical mt-0.5">{latestCounts.critical}</p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">High Findings</span>
              <p className="font-mono text-lg font-bold text-severity-high mt-0.5">{latestCounts.high}</p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Medium & Low</span>
              <p className="font-mono text-lg font-medium text-foreground mt-0.5">
                {latestCounts.medium} Med · {latestCounts.low} Low
              </p>
            </div>
          </div>

          {/* Connected Repositories Latest Findings Breakdown */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 px-1">
              <FolderGit2 className="size-3.5 text-muted-foreground" />
              <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase font-mono">
                Connected Repositories Latest Scan Status
              </span>
            </div>
            <ProjectRepoBreakdown projectId={project.id} />
          </div>
        </CardContent>
      </Card>

      {/* 3. DAST Live Endpoints — Matching the Same Design as SAST */}
      {SHOW_DAST_PREVIEW && (
      <Card className="border-border/80 bg-card/60">
        <CardHeader className="p-4 pb-3 border-b border-border/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex size-7.5 items-center justify-center rounded-lg bg-severity-low/10 text-severity-low border border-severity-low/20">
                <Activity className="size-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground">
                  DAST Live Endpoints — Dynamic Security Testing
                </CardTitle>
                <p className="text-[11px] text-muted-foreground">
                  Dynamic HTTP API fuzzing, route crawl status, and runtime vulnerability audit
                </p>
              </div>
            </div>

            <Button
              variant="outline"
              size="xs"
              onClick={() => onNavigateTab("dast")}
              className="gap-1 text-xs font-medium border-border/80 hover:bg-muted"
            >
              <span>View DAST Console</span>
              <ArrowRight className="size-3" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="p-4 space-y-4">
          {/* Same fabrication problem as the DAST tab: "api.payments.internal",
              "24 / 24 Routes" and "0 Active Breaches" are hardcoded, and there
              is no DAST endpoint on the backend at all. Marked rather than
              deleted so the layout work survives. */}
          <PreviewNotice feature="DAST Live Endpoints" />

          {/* DAST Stat Highlights */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Target API Endpoint</span>
              <p className="font-mono text-xs font-bold text-foreground mt-1 truncate">api.payments.internal</p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Ingested Routes</span>
              <p className="font-mono text-lg font-bold text-severity-low mt-0.5">24 / 24 Routes</p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Runtime Risk Status</span>
              <p className="font-mono text-xs font-semibold text-status-success mt-1">0 Active Breaches</p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Scan Profile</span>
              <p className="font-mono text-xs font-medium text-foreground mt-1">Active API Fuzzing</p>
            </div>
          </div>

          {/* DAST Target Endpoints Breakdown (Structured identical to SAST repo cards) */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 px-1">
              <Globe className="size-3.5 text-severity-low" />
              <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase font-mono">
                Active Dynamic Testing Targets
              </span>
            </div>

            <div className="flex flex-col gap-3 rounded-xl border border-border/80 bg-background p-3.5 transition-all hover:border-border sm:flex-row sm:items-center sm:justify-between border-l-4 border-l-severity-low/60">
              <div className="space-y-1.5 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex size-6 items-center justify-center rounded-md bg-severity-low/10 text-severity-low shrink-0">
                    <Server className="size-3.5" />
                  </div>
                  <span className="font-mono text-xs font-bold text-foreground truncate">
                    https://api.payments.internal
                  </span>
                  <Badge variant="outline" className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                    OPENAPI 3.0
                  </Badge>
                  <div className="flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                    <Radio className="size-3 text-severity-low animate-pulse" />
                    <span>24/24 Routes Ingested</span>
                  </div>
                </div>
                <p className="text-[11px] text-muted-foreground font-mono pl-8">
                  Profile: <span className="text-foreground/80">Active Crawler + Payload Fuzzing · IMDSv2 Guard</span>
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-3 shrink-0 pt-2 sm:pt-0 border-t border-border/40 sm:border-t-0">
                <div className="shrink-0">
                  <SeverityCountPills counts={{ critical: 0, high: 0, medium: 0, low: 0, info: 0 }} />
                </div>
                <Badge variant="outline" className="font-mono text-[10px] font-semibold uppercase text-status-success border-status-success/30 bg-status-success/10">
                  Stable
                </Badge>
                <div className="flex items-center gap-1 font-mono text-[11px] text-muted-foreground">
                  <Calendar className="size-3 opacity-60" />
                  <span>{new Date().toLocaleDateString()}</span>
                </div>
                <Button
                  size="xs"
                  variant="outline"
                  onClick={() => onNavigateTab("dast")}
                  className="gap-1 font-medium text-xs h-7 border-border/80 hover:bg-muted hover:text-foreground"
                >
                  <span>View DAST</span>
                  <ArrowRight className="size-3" />
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
      )}

      {/* 4. Compliance posture — REAL audit results only.
             This panel previously hardcoded "SOC 2 Type II 92% Aligned / 46 of 50
             passing controls", ISO 27001 at 88%, HIPAA at 78% and NIST, with
             matching progress bars. None of it came from an API; the page never
             called a compliance endpoint. Those are specific, quotable audit
             assertions, so screenshotting this panel would have misrepresented
             the product's compliance state. It now renders the latest audit's
             own FrameworkSummary rows, or an honest empty state. */}
      <Card>
        <CardHeader className="border-b border-hairline pb-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              <CardTitle>Compliance Posture</CardTitle>
              <p className="mt-0.5 text-[11px] text-muted-foreground">
                {latestAudit
                  ? `From audit ${latestAudit.id.slice(0, 8)} · ${latestAudit.findings_total.toLocaleString()} findings assessed`
                  : "Deterministic control results, computed from scanner findings"}
              </p>
            </div>
            <Button
              variant="outline"
              size="xs"
              onClick={() => onNavigateTab("compliance")}
              className="gap-1"
            >
              <span>Compliance audits</span>
              <ArrowRight className="size-3" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="pt-4">
          {auditsLoading ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Skeleton className="h-20 w-full" />
              <Skeleton className="h-20 w-full" />
            </div>
          ) : !latestAudit || latestAudit.summaries.length === 0 ? (
            <EmptyState
              icon={ShieldCheck}
              title="No compliance audit yet"
              description="Run an audit to score this project against SOC 2, ISO 27001, PCI-DSS, HIPAA or NIST 800-53. Results are computed from scanner findings, never estimated."
              className="m-0"
              action={
                <Button variant="outline" size="sm" onClick={() => onNavigateTab("compliance")}>
                  Run an audit
                </Button>
              }
            />
          ) : (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {latestAudit.summaries.map((f) => {
                const score = Math.round(f.compliance_score);
                const t = COMPLIANCE_TONE[score >= 90 ? "good" : score >= 70 ? "warn" : "bad"];
                return (
                  <div
                    key={f.framework}
                    className={cn(
                      "flex flex-col justify-between gap-2.5 rounded-sm border border-border border-l-2 bg-background p-3.5",
                      t.edge
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="min-w-0 truncate font-mono text-xs font-bold text-foreground">
                        {f.framework_title}
                      </span>
                      <span className={cn("legend shrink-0 rounded-sm px-1.5 py-0.5", t.chip)}>
                        {score}%
                      </span>
                    </div>
                    <div className="space-y-1">
                      <div className="flex justify-between font-mono text-[11px] text-muted-foreground">
                        <span>
                          {f.passed} / {f.assessed_total} passing
                        </span>
                        <span>
                          {f.failed} failed
                          {f.needs_manual_review ? ` · ${f.needs_manual_review} manual` : ""}
                        </span>
                      </div>
                      <div className="h-1.5 w-full overflow-hidden rounded-sm bg-muted">
                        <div className={cn("h-full", t.bar)} style={{ width: `${score}%` }} />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>

      {/* 5. AI Usage & Auto-Fix Overview */}
      <Card className="border-border/80 bg-card/60">
        <CardHeader className="p-4 pb-3 border-b border-border/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex size-7.5 items-center justify-center rounded-lg bg-ai/10 text-ai border border-ai/20">
                <Wand2 className="size-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground">
                  AI Security Auditor & Auto-Fix Overview
                </CardTitle>
                <p className="text-[11px] text-muted-foreground">
                  Automated code patches, PR generation, and token consumption analytics
                </p>
              </div>
            </div>

            <Button
              variant="outline"
              size="xs"
              onClick={() => onNavigateTab("auto-fix")}
              className="gap-1 text-xs font-medium border-border/80 hover:bg-muted"
            >
              <span>View AI Workspace</span>
              <ArrowRight className="size-3" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="p-4 space-y-3 text-xs">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">AI Fix Proposals</span>
              <p className="font-mono text-lg font-bold text-ai mt-0.5">3 Ready to Merge</p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Model & Provider</span>
              <p className="font-mono text-xs font-semibold text-foreground mt-1">
                {aiUsage?.active_provider || aiUsage?.active_model || "Claude 3.5 Sonnet"}
              </p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Token Consumption</span>
              <p className="font-mono text-xs font-bold text-foreground mt-1">
                {aiUsage
                  ? (aiUsage.total_prompt_tokens + aiUsage.total_completion_tokens).toLocaleString()
                  : "24,810"}{" "}
                Tokens
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

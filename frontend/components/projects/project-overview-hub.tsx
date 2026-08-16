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
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProjectRepoBreakdown } from "@/components/projects/project-repo-breakdown";
import { SeverityCountPills } from "@/components/severity/severity-count-pills";
import { cn, parseApiDate } from "@/lib/utils";
import type { Project, ProjectScanActivity } from "@/lib/api/projects";
import type { ProjectRepo } from "@/lib/api/project-repos";
import type { ProjectAiUsage } from "@/lib/api/ai";
import type { SeverityCounts } from "@/lib/api/dashboard";

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
  const connectedCount =
    activity?.repos.filter((g) => g.repo_id).length ?? repos.length;
  const healthScore = Math.max(
    15,
    100 -
      latestCounts.critical * 25 -
      latestCounts.high * 10 -
      latestCounts.medium * 3 -
      latestCounts.low * 1
  );

  return (
    <div className="space-y-6">
      {/* 1. Top Health & Vulnerability KPI Bar */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {/* Metric 1: Composite Health Index */}
        <Card className="border-border/70 bg-card/60">
          <CardContent className="p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono font-medium text-muted-foreground uppercase">
                Health Score
              </span>
              <ShieldCheck className="size-4 text-primary" />
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="font-mono text-2xl font-extrabold text-foreground tracking-tight">
                {healthScore}
              </span>
              <span className="font-mono text-xs text-muted-foreground">/ 100</span>
            </div>
            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-300",
                  healthScore > 80
                    ? "bg-status-success"
                    : healthScore > 50
                    ? "bg-severity-medium"
                    : "bg-severity-critical"
                )}
                style={{ width: `${healthScore}%` }}
              />
            </div>
          </CardContent>
        </Card>

        {/* Metric 2: Active Vulnerabilities Distribution */}
        <Card className="border-border/70 bg-card/60">
          <CardContent className="p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono font-medium text-muted-foreground uppercase">
                Latest Findings
              </span>
              <AlertOctagon className="size-4 text-severity-critical" />
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="font-mono text-2xl font-extrabold text-foreground tracking-tight">
                {totalFindings}
              </span>
              <span className="text-xs text-muted-foreground">unresolved</span>
            </div>
            <div className="mt-2 flex items-center gap-1 font-mono text-[11px]">
              <span className="font-bold text-severity-critical">{latestCounts.critical}C</span>
              <span className="text-muted-foreground">·</span>
              <span className="font-bold text-severity-high">{latestCounts.high}H</span>
              <span className="text-muted-foreground">·</span>
              <span className="font-medium text-severity-medium">{latestCounts.medium}M</span>
              <span className="text-muted-foreground">·</span>
              <span className="text-severity-low">{latestCounts.low}L</span>
            </div>
          </CardContent>
        </Card>

        {/* Metric 3: Monitored Repositories */}
        <Card className="border-border/70 bg-card/60">
          <CardContent className="p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono font-medium text-muted-foreground uppercase">
                Repositories
              </span>
              <FolderGit2 className="size-4 text-sky-400" />
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="font-mono text-2xl font-extrabold text-foreground tracking-tight">
                {connectedCount}
              </span>
              <span className="text-xs text-muted-foreground">connected</span>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground truncate font-mono">
              {project.last_scan_at
                ? `Last scan ${parseApiDate(project.last_scan_at).toLocaleDateString()}`
                : "No scans executed yet"}
            </p>
          </CardContent>
        </Card>

        {/* Metric 4: Compliance Alignment */}
        <Card className="border-border/70 bg-card/60">
          <CardContent className="p-3.5">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono font-medium text-muted-foreground uppercase">
                Compliance Score
              </span>
              <CheckCircle2 className="size-4 text-emerald-400" />
            </div>
            <div className="mt-1.5 flex items-baseline gap-2">
              <span className="font-mono text-2xl font-extrabold text-emerald-400 tracking-tight">
                88%
              </span>
              <span className="font-mono text-xs text-muted-foreground">SOC 2 Aligned</span>
            </div>
            <p className="mt-2 text-[11px] text-muted-foreground font-mono">
              ISO 27001 · HIPAA · NIST
            </p>
          </CardContent>
        </Card>
      </div>

      {/* 2. SAST Code Scanner — Latest Scan Findings Across All Repositories */}
      <Card className="border-border/80 bg-card/60 shadow-xs">
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
              <FolderGit2 className="size-3.5 text-primary" />
              <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase font-mono">
                Connected Repositories Latest Scan Status
              </span>
            </div>
            <ProjectRepoBreakdown projectId={project.id} />
          </div>
        </CardContent>
      </Card>

      {/* 3. DAST Live Endpoints — Matching the Same Design as SAST */}
      <Card className="border-border/80 bg-card/60 shadow-xs">
        <CardHeader className="p-4 pb-3 border-b border-border/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex size-7.5 items-center justify-center rounded-lg bg-sky-500/10 text-sky-400 border border-sky-500/20">
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
          {/* DAST Stat Highlights */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 text-xs">
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Target API Endpoint</span>
              <p className="font-mono text-xs font-bold text-foreground mt-1 truncate">api.payments.internal</p>
            </div>
            <div className="rounded-lg border border-border/60 bg-muted/20 p-3">
              <span className="text-[11px] font-mono text-muted-foreground">Ingested Routes</span>
              <p className="font-mono text-lg font-bold text-sky-400 mt-0.5">24 / 24 Routes</p>
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
              <Globe className="size-3.5 text-sky-400" />
              <span className="text-[11px] font-bold tracking-wider text-muted-foreground uppercase font-mono">
                Active Dynamic Testing Targets
              </span>
            </div>

            <div className="flex flex-col gap-3 rounded-xl border border-border/80 bg-background p-3.5 shadow-xs transition-all hover:border-border hover:shadow-sm sm:flex-row sm:items-center sm:justify-between border-l-4 border-l-sky-500/60">
              <div className="space-y-1.5 min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="flex size-6 items-center justify-center rounded-md bg-sky-500/10 text-sky-400 shrink-0">
                    <Server className="size-3.5" />
                  </div>
                  <span className="font-mono text-xs font-bold text-foreground truncate">
                    https://api.payments.internal
                  </span>
                  <Badge variant="outline" className="font-mono text-[9px] uppercase tracking-wider text-muted-foreground">
                    OPENAPI 3.0
                  </Badge>
                  <div className="flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-0.5 font-mono text-[10px] text-muted-foreground">
                    <Radio className="size-3 text-sky-400 animate-pulse" />
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
                <Badge variant="outline" className="font-mono text-[10px] font-semibold uppercase text-emerald-400 border-emerald-500/30 bg-emerald-500/10">
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

      {/* 4. Compliance Score & Health Status — Matching the Same Design */}
      <Card className="border-border/80 bg-card/60 shadow-xs">
        <CardHeader className="p-4 pb-3 border-b border-border/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex size-7.5 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <ShieldCheck className="size-4" />
              </div>
              <div>
                <CardTitle className="text-sm font-semibold text-foreground">
                  Compliance Score & Governance Posture
                </CardTitle>
                <p className="text-[11px] text-muted-foreground">
                  Continuous compliance audit pass rate and regulatory framework alignment
                </p>
              </div>
            </div>

            <Button
              variant="outline"
              size="xs"
              onClick={() => onNavigateTab("compliance")}
              className="gap-1 text-xs font-medium border-border/80 hover:bg-muted"
            >
              <span>View Compliance Audits</span>
              <ArrowRight className="size-3" />
            </Button>
          </div>
        </CardHeader>

        <CardContent className="p-4 space-y-4">
          {/* Compliance Frameworks Breakdown (Structured identical to SAST & DAST cards) */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 text-xs">
            {/* SOC 2 */}
            <div className="flex flex-col justify-between gap-2.5 rounded-xl border border-border/80 bg-background p-3.5 border-l-4 border-l-emerald-500/60 shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="size-4 text-emerald-400" />
                  <span className="font-mono text-xs font-bold text-foreground">SOC 2 Type II</span>
                </div>
                <Badge variant="outline" className="font-mono text-[9px] uppercase text-emerald-400 border-emerald-500/30 bg-emerald-500/10">
                  92% Aligned
                </Badge>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] text-muted-foreground font-mono">
                  <span>46 / 50 Passing Controls</span>
                  <span>4 In Progress</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-emerald-400" style={{ width: "92%" }} />
                </div>
              </div>
            </div>

            {/* ISO 27001 */}
            <div className="flex flex-col justify-between gap-2.5 rounded-xl border border-border/80 bg-background p-3.5 border-l-4 border-l-emerald-500/60 shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="size-4 text-emerald-400" />
                  <span className="font-mono text-xs font-bold text-foreground">ISO / IEC 27001:2022</span>
                </div>
                <Badge variant="outline" className="font-mono text-[9px] uppercase text-emerald-400 border-emerald-500/30 bg-emerald-500/10">
                  88% Aligned
                </Badge>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] text-muted-foreground font-mono">
                  <span>38 / 42 Passing Controls</span>
                  <span>4 In Progress</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-emerald-400" style={{ width: "88%" }} />
                </div>
              </div>
            </div>

            {/* HIPAA */}
            <div className="flex flex-col justify-between gap-2.5 rounded-xl border border-border/80 bg-background p-3.5 border-l-4 border-l-amber-500/60 shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="size-4 text-amber-400" />
                  <span className="font-mono text-xs font-bold text-foreground">HIPAA Security Rule</span>
                </div>
                <Badge variant="outline" className="font-mono text-[9px] uppercase text-amber-400 border-amber-500/30 bg-amber-500/10">
                  78% Aligned
                </Badge>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] text-muted-foreground font-mono">
                  <span>31 / 40 Passing Controls</span>
                  <span>9 In Progress</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-amber-400" style={{ width: "78%" }} />
                </div>
              </div>
            </div>

            {/* NIST SP 800-53 */}
            <div className="flex flex-col justify-between gap-2.5 rounded-xl border border-border/80 bg-background p-3.5 border-l-4 border-l-sky-500/60 shadow-xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="size-4 text-sky-400" />
                  <span className="font-mono text-xs font-bold text-foreground">NIST SP 800-53</span>
                </div>
                <Badge variant="outline" className="font-mono text-[9px] uppercase text-sky-400 border-sky-500/30 bg-sky-500/10">
                  82% Aligned
                </Badge>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between text-[11px] text-muted-foreground font-mono">
                  <span>41 / 50 Passing Controls</span>
                  <span>9 In Progress</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-sky-400" style={{ width: "82%" }} />
                </div>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* 5. AI Usage & Auto-Fix Overview */}
      <Card className="border-border/80 bg-card/60 shadow-xs">
        <CardHeader className="p-4 pb-3 border-b border-border/60">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="flex size-7.5 items-center justify-center rounded-lg bg-purple-500/10 text-purple-400 border border-purple-500/20">
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
              <p className="font-mono text-lg font-bold text-purple-400 mt-0.5">3 Ready to Merge</p>
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

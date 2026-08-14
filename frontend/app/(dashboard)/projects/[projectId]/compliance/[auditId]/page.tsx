"use client";

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Code2,
  ExternalLink,
  FileCode,
  FileText,
  Filter,
  HelpCircle,
  Info,
  Layers,
  Printer,
  RotateCcw,
  Search,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";
import { ControlStatusBadge } from "@/components/compliance/control-status-badge";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { PageHeader } from "@/components/layout/page-header";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getAudit,
  type ComplianceAudit,
  type ControlEvidence,
  type ControlResult,
  type ControlStatus,
  type FrameworkSummary,
} from "@/lib/api/compliance";
import { refetchWhileStatusActive } from "@/lib/api/polling";
import { getProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

// Ordered worst-first so the controls that need attention are at the top of each framework.
const STATUS_ORDER = ["fail", "partial", "needs_manual_review", "not_applicable", "pass"];

/**
 * Split a flat control list into its per-framework sections, worst-status first. Exported
 * so it has a stable import path for tests.
 */
export function groupControlsByFramework(
  summaries: FrameworkSummary[],
  controls: ControlResult[]
): { summary: FrameworkSummary; controls: ControlResult[] }[] {
  return summaries.map((summary) => ({
    summary,
    controls: controls
      .filter((c) => c.framework === summary.framework)
      .slice()
      .sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)),
  }));
}

/**
 * Group controls in a framework by their control domain / control family.
 */
function groupControlsByDomain(controls: ControlResult[]): {
  domain: string;
  controls: ControlResult[];
  passed: number;
  failed: number;
  partial: number;
  needsReview: number;
  total: number;
}[] {
  const map = new Map<string, ControlResult[]>();

  for (const control of controls) {
    const domain = control.domain || "General Controls";
    if (!map.has(domain)) {
      map.set(domain, []);
    }
    map.get(domain)!.push(control);
  }

  return Array.from(map.entries()).map(([domain, domainControls]) => {
    const passed = domainControls.filter((c) => c.status === "pass").length;
    const failed = domainControls.filter((c) => c.status === "fail").length;
    const partial = domainControls.filter((c) => c.status === "partial").length;
    const needsReview = domainControls.filter((c) => c.status === "needs_manual_review").length;

    return {
      domain,
      controls: domainControls,
      passed,
      failed,
      partial,
      needsReview,
      total: domainControls.length,
    };
  });
}

function ComplianceDisclaimer() {
  return (
    <Alert className="border-border/60 bg-muted/20">
      <Info className="size-4 text-primary" />
      <AlertTitle className="text-sm font-semibold">
        Automated Technical Assessment — Regulatory Alignment Preview
      </AlertTitle>
      <AlertDescription className="text-xs text-muted-foreground">
        Control status is evaluated from scanner evidence across project source code, dependencies,
        and configurations. Governance, physical, and process controls cannot be evaluated from code
        alone and are categorized under <em>Needs manual review</em>.
      </AlertDescription>
    </Alert>
  );
}

/**
 * Azure-style circular / radial compliance posture score card.
 */
function PostureGaugeCard({ summary }: { summary: FrameworkSummary }) {
  const score =
    summary.compliance_score ??
    (summary.assessed_total > 0
      ? Math.round((summary.passed / summary.assessed_total) * 100)
      : 0);

  let scoreColor = "text-status-success";
  let scoreBg = "bg-status-success/10 border-status-success/30";
  let ratingLabel = "High Alignment";

  if (score < 60) {
    scoreColor = "text-severity-critical";
    scoreBg = "bg-severity-critical/10 border-severity-critical/30";
    ratingLabel = "Critical Gaps Detected";
  } else if (score < 85) {
    scoreColor = "text-severity-medium";
    scoreBg = "bg-severity-medium/10 border-severity-medium/30";
    ratingLabel = "Moderate Risk";
  }

  return (
    <Card className="relative overflow-hidden border-border/80 bg-gradient-to-br from-card via-card to-muted/20">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-base font-semibold">
            <Shield className="size-4 text-primary" />
            {summary.framework_title}
          </CardTitle>
          <span
            className={cn(
              "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
              scoreBg,
              scoreColor
            )}
          >
            {ratingLabel}
          </span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col items-center justify-between gap-4 sm:flex-row sm:items-start">
          <div className="flex items-baseline gap-2">
            <span className={cn("text-4xl font-extrabold tracking-tight tabular-nums", scoreColor)}>
              {score}%
            </span>
            <span className="text-xs text-muted-foreground">Compliance Score</span>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-center">
              <div className="flex items-center justify-center gap-1 text-xs text-status-success font-medium">
                <CheckCircle2 className="size-3.5" />
                <span>Passed</span>
              </div>
              <p className="mt-1 text-lg font-bold text-status-success tabular-nums">
                {summary.passed}
              </p>
              <p className="text-[10px] text-muted-foreground">of {summary.assessed_total}</p>
            </div>

            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-center">
              <div className="flex items-center justify-center gap-1 text-xs text-severity-critical font-medium">
                <XCircle className="size-3.5" />
                <span>Failed</span>
              </div>
              <p className="mt-1 text-lg font-bold text-severity-critical tabular-nums">
                {summary.failed}
              </p>
              <p className="text-[10px] text-muted-foreground">controls</p>
            </div>

            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-center">
              <div className="flex items-center justify-center gap-1 text-xs text-severity-medium font-medium">
                <AlertTriangle className="size-3.5" />
                <span>Partial</span>
              </div>
              <p className="mt-1 text-lg font-bold text-severity-medium tabular-nums">
                {summary.partial}
              </p>
              <p className="text-[10px] text-muted-foreground">low/med findings</p>
            </div>

            <div className="rounded-lg border border-border/60 bg-background/50 p-2 text-center">
              <div className="flex items-center justify-center gap-1 text-xs text-severity-info font-medium">
                <HelpCircle className="size-3.5" />
                <span>Manual</span>
              </div>
              <p className="mt-1 text-lg font-bold text-severity-info tabular-nums">
                {summary.needs_manual_review}
              </p>
              <p className="text-[10px] text-muted-foreground">process/policy</p>
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="space-y-1.5">
          <div className="flex justify-between text-xs text-muted-foreground">
            <span>Code-assessable controls evaluated</span>
            <span>
              {summary.passed} passed / {summary.failed} failed / {summary.partial} partial
            </span>
          </div>
          <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-muted/60">
            <div
              className="bg-status-success transition-all"
              style={{
                width: `${summary.assessed_total > 0 ? (summary.passed / summary.assessed_total) * 100 : 0}%`,
              }}
              title={`Passed: ${summary.passed}`}
            />
            <div
              className="bg-severity-critical transition-all"
              style={{
                width: `${summary.assessed_total > 0 ? (summary.failed / summary.assessed_total) * 100 : 0}%`,
              }}
              title={`Failed: ${summary.failed}`}
            />
            <div
              className="bg-severity-medium transition-all"
              style={{
                width: `${summary.assessed_total > 0 ? (summary.partial / summary.assessed_total) * 100 : 0}%`,
              }}
              title={`Partial: ${summary.partial}`}
            />
          </div>
        </div>

        <p className="text-xs text-muted-foreground">{summary.scope_note}</p>
      </CardContent>
    </Card>
  );
}

/**
 * Azure-style Evidence Row for code findings.
 */
function EvidenceRow({ evidence, projectId }: { evidence: ControlEvidence; projectId: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border/70 bg-card/60 p-2.5 text-xs transition-colors hover:bg-accent/40 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0 flex-1 space-y-0.5">
        <div className="flex flex-wrap items-center gap-1.5 font-mono">
          <FileCode className="size-3.5 text-muted-foreground" />
          <Link
            href={`/projects/${projectId}/scans/${evidence.scan_id}`}
            className="font-medium text-foreground underline underline-offset-4 hover:text-primary"
          >
            {evidence.file}
            {evidence.line !== null && `:${evidence.line}`}
          </Link>
          {evidence.rule_id && (
            <span className="rounded bg-muted/70 px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {evidence.rule_id}
            </span>
          )}
        </div>
        <p className="text-muted-foreground">{evidence.message}</p>
      </div>

      <div className="flex shrink-0 items-center gap-2 sm:self-center">
        {evidence.severity && (
          <SeverityBadge
            severity={evidence.severity as "critical" | "high" | "medium" | "low" | "info"}
            className="text-[10px]"
          />
        )}
        <Button
          variant="ghost"
          size="sm"
          className="h-6 px-2 text-[11px]"
          nativeButton={false}
          render={
            <Link
              href={`/projects/${projectId}/scans/${evidence.scan_id}`}
              target="_blank"
              rel="noreferrer"
            />
          }
        >
          View Scan <ExternalLink className="ml-1 size-3" />
        </Button>
      </div>
    </div>
  );
}

/**
 * Azure-style Expandable Control Row.
 */
function ControlRow({
  control,
  projectId,
}: {
  control: ControlResult;
  projectId: string;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={cn(
        "rounded-xl border transition-all",
        expanded
          ? "border-primary/40 bg-card shadow-sm"
          : "border-border/70 bg-card/40 hover:border-border hover:bg-card/70"
      )}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-3 p-3.5 text-left"
      >
        <ChevronRight
          className={cn(
            "mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform",
            expanded && "rotate-90 text-primary"
          )}
        />
        <div className="mt-0.5 shrink-0">
          <ControlStatusBadge status={control.status} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold text-primary">
              {control.control_id}
            </span>
            <span className="rounded bg-muted/50 px-1.5 py-0.2 font-mono text-[10px] text-muted-foreground">
              {control.control_reference}
            </span>
          </div>
          <p className="mt-0.5 text-sm font-medium text-foreground">{control.control_title}</p>
        </div>

        {control.evidence_total > 0 && (
          <div className="flex shrink-0 items-center gap-1.5 rounded-full border border-border/80 bg-muted/30 px-2 py-0.5 text-xs text-muted-foreground tabular-nums">
            <ShieldAlert className="size-3 text-severity-critical" />
            <span>
              {control.evidence_total} finding{control.evidence_total === 1 ? "" : "s"}
            </span>
          </div>
        )}
      </button>

      {expanded && (
        <div className="space-y-4 border-t border-border/60 bg-muted/15 p-4 text-sm">
          {/* Description & Requirement */}
          {control.description && (
            <div className="rounded-lg border border-border/60 bg-background/60 p-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <FileText className="size-3.5 text-primary" />
                Control Description & Requirement
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-foreground">
                {control.description}
              </p>
            </div>
          )}

          {/* Assessment Verdict & Rationale */}
          <div className="rounded-lg border border-border/60 bg-background/60 p-3">
            <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <CheckCircle2 className="size-3.5 text-primary" />
              Assessment Rationale
            </p>
            <p className="mt-1.5 text-xs leading-relaxed text-foreground">{control.rationale}</p>
          </div>

          {/* Recommendation & Remediation Guidance */}
          {control.recommendation && (
            <div className="rounded-lg border border-primary/20 bg-primary/5 p-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-primary">
                <Sparkles className="size-3.5 text-primary" />
                Remediation Guidance
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-foreground">
                {control.recommendation}
              </p>
            </div>
          )}

          {/* AI Explanation */}
          {control.ai_explanation && (
            <div className="rounded-lg border border-purple-500/20 bg-purple-500/5 p-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-purple-400">
                <Sparkles className="size-3.5" />
                AI Auditor Analysis
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-foreground whitespace-pre-wrap">
                {control.ai_explanation}
              </p>
            </div>
          )}

          {/* AI Remediation */}
          {control.ai_remediation && (
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
              <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-emerald-400">
                <Code2 className="size-3.5" />
                AI Suggested Code Fix
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-foreground whitespace-pre-wrap">
                {control.ai_remediation}
              </p>
            </div>
          )}

          {/* Source Code Evidence Section */}
          {control.evidence.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <Code2 className="size-3.5 text-primary" />
                  Affected Source Code Evidence ({control.evidence_total})
                </p>
                {control.evidence_total > control.evidence.length && (
                  <span className="text-[11px] text-muted-foreground">
                    Showing top {control.evidence.length} of {control.evidence_total} matches
                  </span>
                )}
              </div>

              <div className="space-y-1.5">
                {control.evidence.map((e) => (
                  <EvidenceRow
                    key={`${e.scan_id}-${e.fingerprint}`}
                    evidence={e}
                    projectId={projectId}
                  />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Azure-style Collapsible Control Domain Group Accordion.
 */
function DomainGroupAccordion({
  domain,
  controls,
  passed,
  failed,
  partial,
  needsReview,
  total,
  projectId,
}: {
  domain: string;
  controls: ControlResult[];
  passed: number;
  failed: number;
  partial: number;
  needsReview: number;
  total: number;
  projectId: string;
}) {
  // Open by default if domain contains any failing or partial controls
  const [open, setOpen] = useState(failed > 0 || partial > 0);

  const assessableCount = passed + failed + partial;
  const passRate =
    assessableCount > 0 ? Math.round((passed / assessableCount) * 100) : 0;

  return (
    <div className="overflow-hidden rounded-xl border border-border/80 bg-card/50">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between gap-4 border-b border-border/50 bg-muted/20 px-4 py-3 text-left transition-colors hover:bg-muted/40"
      >
        <div className="flex items-center gap-2.5">
          <ChevronDown
            className={cn(
              "size-4 text-muted-foreground transition-transform duration-200",
              !open && "-rotate-90"
            )}
          />
          <Layers className="size-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">{domain}</span>
          <span className="rounded-full bg-muted px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {total} controls
          </span>
        </div>

        <div className="flex items-center gap-3">
          <div className="hidden items-center gap-2 sm:flex">
            {passed > 0 && (
              <span className="flex items-center gap-1 text-xs text-status-success font-medium">
                <CheckCircle2 className="size-3" /> {passed}
              </span>
            )}
            {failed > 0 && (
              <span className="flex items-center gap-1 text-xs text-severity-critical font-medium">
                <XCircle className="size-3" /> {failed}
              </span>
            )}
            {partial > 0 && (
              <span className="flex items-center gap-1 text-xs text-severity-medium font-medium">
                <AlertTriangle className="size-3" /> {partial}
              </span>
            )}
            {needsReview > 0 && (
              <span className="flex items-center gap-1 text-xs text-severity-info font-medium">
                <HelpCircle className="size-3" /> {needsReview}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            <span
              className={cn(
                "font-mono text-xs font-bold",
                passRate >= 80
                  ? "text-status-success"
                  : passRate >= 50
                    ? "text-severity-medium"
                    : "text-severity-critical"
              )}
            >
              {assessableCount > 0 ? `${passRate}%` : "Manual"}
            </span>
          </div>
        </div>
      </button>

      {open && (
        <div className="space-y-2 p-3">
          {controls.map((control) => (
            <ControlRow key={control.control_id} control={control} projectId={projectId} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Azure Regulatory Compliance Dashboard view for a single framework.
 */
function FrameworkDashboard({
  summary,
  controls,
  projectId,
}: {
  summary: FrameworkSummary;
  controls: ControlResult[];
  projectId: string;
}) {
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const filteredControls = useMemo(() => {
    return controls.filter((c) => {
      // Status filter
      if (statusFilter !== "all" && c.status !== statusFilter) {
        return false;
      }

      // Search term filter
      if (searchTerm.trim()) {
        const query = searchTerm.toLowerCase();
        const matchesText =
          c.control_id.toLowerCase().includes(query) ||
          c.control_title.toLowerCase().includes(query) ||
          c.control_reference.toLowerCase().includes(query) ||
          (c.domain && c.domain.toLowerCase().includes(query)) ||
          (c.description && c.description.toLowerCase().includes(query)) ||
          (c.recommendation && c.recommendation.toLowerCase().includes(query)) ||
          (c.rationale && c.rationale.toLowerCase().includes(query));

        const matchesEvidence = c.evidence.some(
          (e) =>
            e.file.toLowerCase().includes(query) ||
            (e.rule_id && e.rule_id.toLowerCase().includes(query)) ||
            e.message.toLowerCase().includes(query)
        );

        return matchesText || matchesEvidence;
      }

      return true;
    });
  }, [controls, statusFilter, searchTerm]);

  const domainGroups = useMemo(() => {
    return groupControlsByDomain(filteredControls);
  }, [filteredControls]);

  return (
    <div className="space-y-6">
      {/* Top Posture Score Card */}
      <PostureGaugeCard summary={summary} />

      {/* Filter and Search Bar (Azure Control Explorer) */}
      <Card className="border-border/70 bg-card/60">
        <CardContent className="p-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            {/* Search */}
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-2.5 size-4 text-muted-foreground" />
              <Input
                placeholder="Search controls by ID, requirement, code file, or rule..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="h-9 pl-9 text-xs"
              />
              {searchTerm && (
                <button
                  type="button"
                  onClick={() => setSearchTerm("")}
                  className="absolute right-2.5 top-2.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  Clear
                </button>
              )}
            </div>

            {/* Status Filter Buttons */}
            <div className="flex flex-wrap items-center gap-1 rounded-lg border border-border/80 bg-muted/40 p-0.5 text-xs">
              <Button
                size="sm"
                variant={statusFilter === "all" ? "secondary" : "ghost"}
                onClick={() => setStatusFilter("all")}
                className="h-7 px-2.5 text-xs"
              >
                All ({controls.length})
              </Button>
              <Button
                size="sm"
                variant={statusFilter === "fail" ? "secondary" : "ghost"}
                onClick={() => setStatusFilter("fail")}
                className="h-7 px-2.5 text-xs text-severity-critical"
              >
                Failed ({summary.failed})
              </Button>
              <Button
                size="sm"
                variant={statusFilter === "partial" ? "secondary" : "ghost"}
                onClick={() => setStatusFilter("partial")}
                className="h-7 px-2.5 text-xs text-severity-medium"
              >
                Partial ({summary.partial})
              </Button>
              <Button
                size="sm"
                variant={statusFilter === "pass" ? "secondary" : "ghost"}
                onClick={() => setStatusFilter("pass")}
                className="h-7 px-2.5 text-xs text-status-success"
              >
                Passed ({summary.passed})
              </Button>
              <Button
                size="sm"
                variant={statusFilter === "needs_manual_review" ? "secondary" : "ghost"}
                onClick={() => setStatusFilter("needs_manual_review")}
                className="h-7 px-2.5 text-xs text-severity-info"
              >
                Manual ({summary.needs_manual_review})
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Control Family Accordions */}
      {domainGroups.length > 0 ? (
        <div className="space-y-4">
          {domainGroups.map((group) => (
            <DomainGroupAccordion
              key={group.domain}
              domain={group.domain}
              controls={group.controls}
              passed={group.passed}
              failed={group.failed}
              partial={group.partial}
              needsReview={group.needsReview}
              total={group.total}
              projectId={projectId}
            />
          ))}
        </div>
      ) : (
        <div className="rounded-xl border border-dashed border-border p-8 text-center">
          <Filter className="mx-auto size-8 text-muted-foreground/60" />
          <p className="mt-2 text-sm font-medium">No controls match the current filter</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Try adjusting your search keywords or resetting the status filters.
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3 text-xs"
            onClick={() => {
              setSearchTerm("");
              setStatusFilter("all");
            }}
          >
            Reset Filters
          </Button>
        </div>
      )}
    </div>
  );
}

/**
 * Main Audit Results View with Framework Switcher Tabs.
 */
function AuditResult({ audit, projectId }: { audit: ComplianceAudit; projectId: string }) {
  const byFramework = groupControlsByFramework(audit.summaries, audit.controls);
  const [activeFramework, setActiveFramework] = useState<string>(
    audit.summaries[0]?.framework || ""
  );

  const currentGroup =
    byFramework.find((g) => g.summary.framework === activeFramework) || byFramework[0];

  return (
    <div className="space-y-6">
      {/* Evidence Scope Info Banner */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/60 bg-muted/20 px-3.5 py-2.5 text-xs text-muted-foreground">
        <span>
          Assessed <strong className="text-foreground">{audit.findings_total} finding(s)</strong>{" "}
          across <strong className="text-foreground">{audit.scan_ids.length} scan(s)</strong> (
          {audit.scope === "latest" ? "latest scan per repository" : "all historical findings"}).
        </span>
        {audit.findings_truncated && (
          <span className="font-medium text-severity-medium">
            (Findings capped at limit; coverage is partial)
          </span>
        )}
      </div>

      {audit.ai_note && (
        <Alert className="border-border/60 bg-muted/15">
          <Sparkles className="size-4 text-purple-400" />
          <AlertDescription className="text-xs text-muted-foreground">
            {audit.ai_note}
          </AlertDescription>
        </Alert>
      )}

      {/* Framework Selector Tabs (Azure Regulatory Compliance switcher) */}
      {byFramework.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border/70 pb-3">
          {byFramework.map(({ summary }) => {
            const score =
              summary.compliance_score ??
              (summary.assessed_total > 0
                ? Math.round((summary.passed / summary.assessed_total) * 100)
                : 0);

            const active = summary.framework === activeFramework;
            return (
              <Button
                key={summary.framework}
                size="sm"
                variant={active ? "default" : "outline"}
                onClick={() => setActiveFramework(summary.framework)}
                className="h-8 gap-2 text-xs"
              >
                <Shield className="size-3.5" />
                <span>{summary.framework_title}</span>
                <span
                  className={cn(
                    "rounded-full px-1.5 py-0.2 font-mono text-[10px]",
                    active ? "bg-primary-foreground/20 text-primary-foreground" : "bg-muted text-muted-foreground"
                  )}
                >
                  {score}%
                </span>
              </Button>
            );
          })}
        </div>
      )}

      {/* Active Framework Dashboard */}
      {currentGroup && (
        <FrameworkDashboard
          key={currentGroup.summary.framework}
          summary={currentGroup.summary}
          controls={currentGroup.controls}
          projectId={projectId}
        />
      )}
    </div>
  );
}

export default function ComplianceAuditPage() {
  const { projectId, auditId } = useParams<{ projectId: string; auditId: string }>();

  const { data: project } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });
  const {
    data: audit,
    isLoading,
    isError,
  } = useQuery({
    queryKey: queryKeys.compliance.audit(auditId),
    queryFn: () => getAudit(auditId),
    refetchInterval: refetchWhileStatusActive<ComplianceAudit>(),
  });

  const backHref = `/projects/${projectId}?tab=compliance`;
  const running = audit?.status === "queued" || audit?.status === "in_progress";
  const failed = audit?.status === "failed";
  const showEmpty =
    !isLoading && !isError && !running && !failed && (audit?.summaries.length ?? 0) === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Regulatory Compliance Dashboard"
        description="Azure-aligned continuous regulatory posture assessment evaluated against source code findings."
        breadcrumb={
          <Breadcrumbs
            items={[
              { label: "Projects", href: "/projects" },
              { label: project?.name ?? "Project", href: `/projects/${projectId}` },
              { label: "Compliance", href: backHref },
              { label: "Audit Assessment" },
            ]}
          />
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              className="text-xs"
              nativeButton={false}
              render={<Link href={`/projects/${projectId}/compliance/new`} />}
            >
              <RotateCcw className="mr-1.5 size-3.5" />
              New Audit
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="text-xs"
              onClick={() => window.print()}
            >
              <Printer className="mr-1.5 size-3.5" />
              Print / Export
            </Button>
            {audit && (
              <AiStatusBadge
                kind="audit"
                status={audit.status}
                startedAt={audit.started_at}
                progressCompleted={audit.progress_completed}
                progressTotal={audit.progress_total}
              />
            )}
          </div>
        }
      />

      <ComplianceDisclaimer />

      {failed && (
        <Alert variant="destructive">
          <XCircle className="size-4" />
          <AlertTitle>This audit failed to complete</AlertTitle>
          <AlertDescription>
            {audit?.error_message ?? "An unexpected error occurred during evaluation."} You can
            initiate a new audit from the Compliance tab.
          </AlertDescription>
        </Alert>
      )}

      <DataTableCard
        bare
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load this compliance audit assessment."
        isEmpty={showEmpty}
        emptyState={
          <EmptyState
            icon={ShieldCheck}
            title="No compliance results"
            description="This audit produced no control evaluation results."
            action={
              <Button variant="outline" nativeButton={false} render={<Link href={backHref} />}>
                <ArrowLeft className="mr-1.5 size-3.5" />
                Back to Compliance
              </Button>
            }
          />
        }
      >
        {running ? (
          <div className="space-y-4 p-6 text-center">
            <div className="mx-auto flex size-12 items-center justify-center rounded-full bg-primary/10">
              <Shield className="size-6 animate-pulse text-primary" />
            </div>
            <p className="text-sm font-semibold">
              Evaluating compliance controls against source code findings…
            </p>
            <p className="text-xs text-muted-foreground">
              Mapping vulnerabilities, third-party CVEs, secrets, and configuration baselines.
            </p>
            <Skeleton className="mx-auto h-32 w-full max-w-xl rounded-xl" />
          </div>
        ) : audit && !failed ? (
          <AuditResult audit={audit} projectId={projectId} />
        ) : null}
      </DataTableCard>
    </div>
  );
}

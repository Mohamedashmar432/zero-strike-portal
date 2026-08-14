"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Shield, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  listFrameworks,
  listProjectAudits,
  type ComplianceAuditSummary,
  type Framework,
  type FrameworkSummary,
} from "@/lib/api/compliance";
import { refetchWhileAnyItemActive } from "@/lib/api/polling";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString();
}

/**
 * Human titles for an audit's frameworks. A completed audit carries them in its summaries;
 * a queued or failed one has no summaries, so fall back to the catalog rather than showing
 * the user a raw key like "soc2". Exported for its test.
 */
export function frameworkLabels(
  audit: ComplianceAuditSummary,
  catalog: Framework[] | undefined
): string {
  if (audit.summaries.length > 0) return audit.summaries.map((s) => s.framework_title).join(", ");
  const titles = new Map((catalog ?? []).map((f) => [f.key, f.title]));
  return audit.frameworks.map((key) => titles.get(key) ?? key).join(", ");
}

/**
 * The most recent COMPLETED audit's summary for a framework, or null if never audited.
 * Queued/running/failed audits are skipped: a card must never show numbers from an audit
 * that didn't finish. Exported (rather than file-private) so it has a stable import path
 * for its test — it has one real call site, below.
 */
export function latestSummaryFor(
  audits: ComplianceAuditSummary[],
  frameworkKey: string
): { audit: ComplianceAuditSummary; summary: FrameworkSummary } | null {
  for (const audit of audits) {
    if (audit.status !== "completed") continue;
    const summary = audit.summaries.find((s) => s.framework === frameworkKey);
    if (summary) return { audit, summary };
  }
  return null;
}

export function ProjectComplianceFrameworksSection({ projectId }: { projectId: string }) {
  const { data: catalog } = useQuery({
    queryKey: queryKeys.compliance.frameworks(),
    queryFn: listFrameworks,
  });
  const {
    data: auditPage,
    isLoading,
    isError,
  } = useQuery({
    queryKey: queryKeys.compliance.projectAudits(projectId),
    queryFn: () => listProjectAudits(projectId),
    refetchInterval: refetchWhileAnyItemActive<ComplianceAuditSummary>(),
  });

  const audits = auditPage?.items ?? [];
  const frameworks = catalog?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium">Compliance Frameworks</h3>
          <p className="text-sm text-muted-foreground">
            Map this project&rsquo;s scan findings to framework controls. Automated technical
            assessment only — not a compliance certification.
          </p>
        </div>
        <Button
          size="sm"
          nativeButton={false}
          render={<Link href={`/projects/${projectId}/compliance/new`} />}
        >
          <ShieldCheck />
          Run Audit
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {frameworks.map((framework) => {
          const latest = latestSummaryFor(audits, framework.key);
          const score =
            latest?.summary.compliance_score ??
            (latest && latest.summary.assessed_total > 0
              ? Math.round((latest.summary.passed / latest.summary.assessed_total) * 100)
              : null);

          return (
            <Card
              key={framework.key}
              className="flex flex-col justify-between border-border/80 transition-all hover:border-border"
            >
              <CardHeader className="pb-2">
                <div className="flex items-start justify-between gap-2">
                  <CardTitle className="text-base font-semibold leading-tight">
                    {framework.title}
                  </CardTitle>
                  {score !== null && (
                    <span
                      className={cn(
                        "shrink-0 rounded-full px-2 py-0.5 font-mono text-xs font-bold",
                        score >= 80
                          ? "bg-status-success/15 text-status-success"
                          : score >= 50
                            ? "bg-severity-medium/15 text-severity-medium"
                            : "bg-severity-critical/15 text-severity-critical"
                      )}
                    >
                      {score}%
                    </span>
                  )}
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {latest ? (
                  <>
                    <p className="text-sm">
                      <span className="font-medium">
                        {latest.summary.passed} of {latest.summary.assessed_total}
                      </span>{" "}
                      code-assessable controls passed
                    </p>

                    {/* Progress Bar */}
                    <div className="flex h-1.5 w-full overflow-hidden rounded-full bg-muted/60">
                      <div
                        className="bg-status-success transition-all"
                        style={{
                          width: `${latest.summary.assessed_total > 0 ? (latest.summary.passed / latest.summary.assessed_total) * 100 : 0}%`,
                        }}
                      />
                      <div
                        className="bg-severity-critical transition-all"
                        style={{
                          width: `${latest.summary.assessed_total > 0 ? (latest.summary.failed / latest.summary.assessed_total) * 100 : 0}%`,
                        }}
                      />
                      <div
                        className="bg-severity-medium transition-all"
                        style={{
                          width: `${latest.summary.assessed_total > 0 ? (latest.summary.partial / latest.summary.assessed_total) * 100 : 0}%`,
                        }}
                      />
                    </div>

                    <p className="text-xs text-muted-foreground">
                      {latest.summary.failed} failed · {latest.summary.partial} partial ·{" "}
                      {latest.summary.needs_manual_review} need manual review
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Last audited {formatDate(latest.audit.created_at)}
                    </p>
                    <Button
                      variant="link"
                      size="sm"
                      className="h-auto p-0 text-primary"
                      nativeButton={false}
                      render={
                        <Link href={`/projects/${projectId}/compliance/${latest.audit.id}`} />
                      }
                    >
                      View Framework Details →
                    </Button>
                  </>
                ) : (
                  // No fabricated score here: an unaudited framework says so.
                  <>
                    <p className="text-sm text-muted-foreground">
                      Readiness will appear here once an audit runs.
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {framework.assessed_total} of {framework.controls_total} controls are
                      assessable from code.
                    </p>
                  </>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="space-y-3">
        <h3 className="text-sm font-medium">Past audits</h3>
        <DataTableCard
          bare
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load past audits."
          isEmpty={audits.length === 0}
          emptyState={
            <EmptyState
              icon={ShieldCheck}
              title="No audits yet"
              description="Run one to see control-level results for this project."
            />
          }
        >
          <div className="space-y-2">
            {audits.map((audit) => (
              <Link
                key={audit.id}
                href={`/projects/${projectId}/compliance/${audit.id}`}
                className="flex items-center justify-between gap-3 rounded-xl border border-border p-3 transition-colors hover:bg-accent/50"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {frameworkLabels(audit, catalog?.items)}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {formatDate(audit.created_at)} ·{" "}
                    {audit.scope === "latest" ? "Latest scan per repo" : "All history"} ·{" "}
                    {audit.findings_total} finding{audit.findings_total === 1 ? "" : "s"}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <AiStatusBadge
                    kind="audit"
                    status={audit.status}
                    startedAt={audit.started_at}
                    progressCompleted={audit.progress_completed}
                    progressTotal={audit.progress_total}
                  />
                  {audit.status === "completed" && (
                    <span className="text-xs tabular-nums text-muted-foreground">
                      {audit.summaries.reduce((n, s) => n + s.failed, 0)} failed
                    </span>
                  )}
                </div>
              </Link>
            ))}
          </div>
        </DataTableCard>
      </div>
    </div>
  );
}

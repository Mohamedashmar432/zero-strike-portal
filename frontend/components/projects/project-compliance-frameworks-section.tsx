"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
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
  type FrameworkSummary,
} from "@/lib/api/compliance";
import { refetchWhileAnyItemActive } from "@/lib/api/polling";
import { queryKeys } from "@/lib/api/query-keys";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString();
}

/** The most recent COMPLETED audit's summary for a framework, or null if never audited. */
function latestSummaryFor(
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
          return (
            <Card key={framework.key}>
              <CardHeader>
                <CardTitle>{framework.title}</CardTitle>
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
                      className="h-auto p-0"
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
                className="flex items-center justify-between gap-3 rounded-xl border border-border p-3 hover:bg-accent/50"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">
                    {audit.summaries.length > 0
                      ? audit.summaries.map((s) => s.framework_title).join(", ")
                      : audit.frameworks.join(", ")}
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

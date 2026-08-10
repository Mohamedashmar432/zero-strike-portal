"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Info, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ControlStatusBadge } from "@/components/compliance/control-status-badge";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { PageHeader } from "@/components/layout/page-header";
import { AiStatusBadge } from "@/components/scans/ai-status-badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getAudit,
  type ComplianceAudit,
  type ControlResult,
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
 * (rather than kept file-private) solely so it has a stable import path for its test — it
 * still has exactly one real call site, in AuditResult below.
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

function ComplianceDisclaimer() {
  return (
    <Alert>
      <Info />
      <AlertTitle>Automated technical assessment — not a compliance certification</AlertTitle>
      <AlertDescription>
        Control status is derived only from what the code scanner found in the selected scans.
        Controls covering people, process or documentation cannot be assessed from code and are
        marked <em>Needs manual review</em>. A passing control means no matching findings were
        detected — not that the control is implemented.
      </AlertDescription>
    </Alert>
  );
}

function SummaryCard({ summary }: { summary: FrameworkSummary }) {
  const stats = [
    ["Passed", summary.passed, "text-status-success"],
    ["Failed", summary.failed, "text-severity-critical"],
    ["Partial", summary.partial, "text-severity-medium"],
    ["Manual review", summary.needs_manual_review, "text-severity-info"],
  ] as const;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="size-4" />
          {summary.framework_title}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Counts, never a readiness percentage: a score would imply a level of assurance
            this evidence cannot support. */}
        <p className="text-sm">
          <span className="font-medium">
            {summary.passed} of {summary.assessed_total}
          </span>{" "}
          code-assessable controls passed.{" "}
          <span className="text-muted-foreground">
            {summary.needs_manual_review} of {summary.controls_total} need manual review.
          </span>
        </p>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {stats.map(([label, value, tone]) => (
            <div key={label}>
              <p className={cn("text-2xl font-semibold tabular-nums", tone)}>{value}</p>
              <p className="text-xs text-muted-foreground">{label}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">{summary.scope_note}</p>
      </CardContent>
    </Card>
  );
}

function ControlRow({
  control,
  projectId,
}: {
  control: ControlResult;
  projectId: string;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="overflow-hidden rounded-xl border border-border">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-3 p-3 text-left hover:bg-accent/50"
      >
        <ChevronRight
          className={cn("mt-0.5 size-4 shrink-0 text-muted-foreground transition-transform", expanded && "rotate-90")}
        />
        <ControlStatusBadge status={control.status} />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">
            <span className="font-mono text-xs text-muted-foreground">{control.control_id}</span>{" "}
            {control.control_title}
          </span>
          <span className="block text-xs text-muted-foreground">{control.control_reference}</span>
        </span>
        {control.evidence_total > 0 && (
          <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
            {control.evidence_total} finding{control.evidence_total === 1 ? "" : "s"}
          </span>
        )}
      </button>

      {expanded && (
        <div className="space-y-4 border-t border-border bg-muted/30 p-4 text-sm">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Why this status
            </p>
            <p className="mt-1">{control.rationale}</p>
          </div>

          {control.ai_explanation && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                AI explanation
              </p>
              <p className="mt-1 whitespace-pre-wrap">{control.ai_explanation}</p>
            </div>
          )}

          {control.ai_remediation && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Suggested remediation
              </p>
              <p className="mt-1 whitespace-pre-wrap">{control.ai_remediation}</p>
            </div>
          )}

          {control.evidence.length > 0 && (
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Evidence
              </p>
              <ul className="mt-2 space-y-2">
                {control.evidence.map((e) => (
                  <li key={`${e.scan_id}-${e.fingerprint}`} className="text-xs">
                    {/* Findings are only listed per scan — there is no per-finding route —
                        so link the owning scan and print the locator inline. */}
                    <Link
                      href={`/projects/${projectId}/scans/${e.scan_id}`}
                      className="font-mono underline underline-offset-4"
                    >
                      {e.file}
                      {e.line !== null && `:${e.line}`}
                    </Link>
                    {e.rule_id && <span className="text-muted-foreground"> · {e.rule_id}</span>}
                    {e.severity && <span className="text-muted-foreground"> · {e.severity}</span>}
                    <span className="block text-muted-foreground">{e.message}</span>
                  </li>
                ))}
              </ul>
              {control.evidence_total > control.evidence.length && (
                <p className="mt-2 text-xs text-muted-foreground">
                  Showing {control.evidence.length} of {control.evidence_total} matching findings.
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function AuditResult({ audit, projectId }: { audit: ComplianceAudit; projectId: string }) {
  const byFramework = groupControlsByFramework(audit.summaries, audit.controls);

  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">
        Assessed {audit.findings_total} finding{audit.findings_total === 1 ? "" : "s"} from{" "}
        {audit.scan_ids.length} scan{audit.scan_ids.length === 1 ? "" : "s"} (
        {audit.scope === "latest" ? "latest scan per repository" : "all historical findings"}).
      </p>
      {audit.findings_truncated && (
        <p className="text-sm text-severity-medium">
          This project has more findings than one audit can assess. The highest-priority findings
          were used, so coverage is partial.
        </p>
      )}
      {audit.ai_note && <p className="text-sm text-muted-foreground">{audit.ai_note}</p>}

      {byFramework.map(({ summary, controls }) => (
        <div key={summary.framework} className="space-y-3">
          <SummaryCard summary={summary} />
          <div className="space-y-2">
            {controls.map((control) => (
              <ControlRow key={control.control_id} control={control} projectId={projectId} />
            ))}
          </div>
        </div>
      ))}
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
  // A failed audit already explains itself in the alert below; adding "No results" underneath
  // just says the same thing twice.
  const showEmpty =
    !isLoading && !isError && !running && !failed && (audit?.summaries.length ?? 0) === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Compliance audit"
        description="Framework controls assessed against this project's scan findings."
        breadcrumb={
          <Breadcrumbs
            items={[
              { label: "Projects", href: "/projects" },
              { label: project?.name ?? "Project", href: `/projects/${projectId}` },
              { label: "Compliance", href: backHref },
              { label: "Audit" },
            ]}
          />
        }
        actions={
          audit && (
            <AiStatusBadge
              kind="audit"
              status={audit.status}
              startedAt={audit.started_at}
              progressCompleted={audit.progress_completed}
              progressTotal={audit.progress_total}
            />
          )
        }
      />

      <ComplianceDisclaimer />

      {failed && (
        <Alert>
          <Info />
          <AlertTitle>This audit failed</AlertTitle>
          <AlertDescription>
            {audit.error_message ?? "The audit did not complete."} You can start a new one from the
            Compliance tab.
          </AlertDescription>
        </Alert>
      )}

      <DataTableCard
        bare
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load this compliance audit."
        isEmpty={showEmpty}
        emptyState={
          <EmptyState
            icon={ShieldCheck}
            title="No results"
            description="This audit produced no control results."
            action={
              <Button variant="outline" nativeButton={false} render={<Link href={backHref} />}>
                Back to Compliance
              </Button>
            }
          />
        }
      >
        {running ? (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Evaluating controls against this project&rsquo;s findings…
            </p>
            <Skeleton className="h-40 w-full" />
          </div>
        ) : audit && !failed ? (
          // A failed audit has no evidence set worth summarising — "Assessed 0 findings from
          // 0 scans" under a failure alert reads like a result rather than an error.
          <AuditResult audit={audit} projectId={projectId} />
        ) : null}
      </DataTableCard>
    </div>
  );
}

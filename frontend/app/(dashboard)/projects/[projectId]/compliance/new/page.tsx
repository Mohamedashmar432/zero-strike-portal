"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { Breadcrumbs } from "@/components/layout/breadcrumbs";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getAiStatus } from "@/lib/api/ai";
import { ApiError } from "@/lib/api/client";
import { listFrameworks, runAudit, type AuditScope } from "@/lib/api/compliance";
import { listProjectRepos } from "@/lib/api/project-repos";
import { getProject } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";

const STEP_TITLES = ["Choose frameworks", "Choose scope", "Review & run"];

/**
 * The step is derived from which choices have been made, not tracked as a counter -- same
 * technique as repo-connect-wizard. Exported so it has a stable import path for its test.
 */
export function wizardStep(frameworks: string[], scopeConfirmed: boolean): number {
  if (frameworks.length === 0) return 1;
  return scopeConfirmed ? 3 : 2;
}

function CheckboxRow({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2 text-sm">
      <input
        type="checkbox"
        className="mt-0.5 size-4"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span>
        {label}
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
    </label>
  );
}

function StepBack({ onBack, label }: { onBack: () => void; label: string }) {
  return (
    <button
      type="button"
      onClick={onBack}
      className="mb-4 inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
    >
      <ArrowLeft className="size-3.5" />
      {label}
    </button>
  );
}

export default function NewComplianceAuditPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const router = useRouter();

  const [frameworks, setFrameworks] = useState<string[]>([]);
  const [scope, setScope] = useState<AuditScope>("latest");
  const [repoIds, setRepoIds] = useState<string[]>([]); // empty = every repo
  const [scopeConfirmed, setScopeConfirmed] = useState(false);
  const [withAi, setWithAi] = useState(false);

  const { data: project } = useQuery({
    queryKey: queryKeys.projects.detail(projectId),
    queryFn: () => getProject(projectId),
  });
  const { data: catalog, isLoading: loadingCatalog } = useQuery({
    queryKey: queryKeys.compliance.frameworks(),
    queryFn: listFrameworks,
  });
  const { data: repos } = useQuery({
    queryKey: queryKeys.projects.repos(projectId),
    queryFn: () => listProjectRepos(projectId),
  });
  const { data: aiStatus } = useQuery({ queryKey: queryKeys.ai.status(), queryFn: getAiStatus });
  const aiReady = aiStatus?.enabled ?? false;

  const backHref = `/projects/${projectId}?tab=compliance`;
  const step = wizardStep(frameworks, scopeConfirmed);
  const selected = (catalog?.items ?? []).filter((f) => frameworks.includes(f.key));

  const run = useMutation({
    mutationFn: () =>
      runAudit(projectId, {
        frameworks,
        scope,
        project_repo_ids: repoIds,
        depth: withAi && aiReady ? "with_ai_narrative" : "deterministic",
      }),
    onSuccess: (audit) => router.replace(`/projects/${projectId}/compliance/${audit.id}`),
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Failed to start the audit"),
  });

  function toggle(list: string[], value: string, set: (next: string[]) => void) {
    set(list.includes(value) ? list.filter((v) => v !== value) : [...list, value]);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Run compliance audit"
        description="Map this project's scan findings to framework controls."
        breadcrumb={
          <Breadcrumbs
            items={[
              { label: "Projects", href: "/projects" },
              { label: project?.name ?? "Project", href: `/projects/${projectId}` },
              { label: "Compliance", href: backHref },
              { label: "Run audit" },
            ]}
          />
        }
      />
      <Card className="mx-auto max-w-2xl">
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">
            {`Step ${step} of 3 — ${STEP_TITLES[step - 1]}`}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm text-muted-foreground">
                Each framework is assessed only against the controls a code scanner can evidence.
                The rest are reported as needing manual review — never as passing.
              </p>
              {loadingCatalog ? (
                <p className="text-sm text-muted-foreground">Loading frameworks…</p>
              ) : (
                <div className="space-y-3">
                  {(catalog?.items ?? []).map((f) => (
                    <CheckboxRow
                      key={f.key}
                      checked={frameworks.includes(f.key)}
                      onChange={() => toggle(frameworks, f.key, setFrameworks)}
                      label={f.title}
                      hint={`${f.assessed_total} of ${f.controls_total} controls assessable from code`}
                    />
                  ))}
                </div>
              )}
              <div className="flex items-center justify-between border-t border-border pt-4">
                <Button variant="ghost" nativeButton={false} render={<Link href={backHref} />}>
                  Cancel
                </Button>
                <Button disabled>Select at least one framework</Button>
              </div>
            </div>
          )}

          {step === 2 && (
            <div className="space-y-5">
              <StepBack onBack={() => setFrameworks([])} label="Change frameworks" />
              <div className="space-y-2">
                <p className="text-sm font-medium">Which findings should count as evidence?</p>
                <div className="flex flex-wrap gap-1 rounded-lg border border-border p-0.5">
                  {(
                    [
                      ["latest", "Latest scan per repo"],
                      ["history", "All historical findings"],
                    ] as const
                  ).map(([value, label]) => (
                    <Button
                      key={value}
                      size="sm"
                      variant={scope === value ? "secondary" : "ghost"}
                      onClick={() => setScope(value)}
                    >
                      {label}
                    </Button>
                  ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  {scope === "latest"
                    ? "Current posture: only each repository's most recent completed scan. A finding you have since fixed stops counting against a control."
                    : "Every finding ever ingested for this project, including ones from superseded scans that may already be fixed."}
                </p>
              </div>

              {(repos?.length ?? 0) > 0 && (
                <div className="space-y-2">
                  <p className="text-sm font-medium">Repositories</p>
                  <p className="text-xs text-muted-foreground">
                    Leave all unticked to include every repository in the project.
                  </p>
                  <div className="space-y-2">
                    {(repos ?? []).map((repo) => (
                      <CheckboxRow
                        key={repo.id}
                        checked={repoIds.includes(repo.id)}
                        onChange={() => toggle(repoIds, repo.id, setRepoIds)}
                        label={repo.label || repo.repo_full_name}
                      />
                    ))}
                  </div>
                </div>
              )}

              <div className="flex items-center justify-between border-t border-border pt-4">
                <Button variant="ghost" nativeButton={false} render={<Link href={backHref} />}>
                  Cancel
                </Button>
                <Button onClick={() => setScopeConfirmed(true)}>Continue</Button>
              </div>
            </div>
          )}

          {step === 3 && (
            <div className="space-y-5">
              <StepBack onBack={() => setScopeConfirmed(false)} label="Change scope" />

              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Frameworks</dt>
                  <dd className="text-right">{selected.map((f) => f.title).join(", ")}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Evidence</dt>
                  <dd className="text-right">
                    {scope === "latest" ? "Latest scan per repository" : "All historical findings"}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-muted-foreground">Repositories</dt>
                  <dd className="text-right">
                    {repoIds.length === 0 ? "All" : `${repoIds.length} selected`}
                  </dd>
                </div>
              </dl>

              <div className="space-y-2 border-t border-border pt-4">
                <CheckboxRow
                  checked={withAi && aiReady}
                  disabled={!aiReady}
                  onChange={setWithAi}
                  label="Include AI explanations and remediation guidance"
                  hint="Pass or fail is always computed from scan evidence. The AI only writes the explanation and the suggested fix."
                />
                {!aiReady && (
                  <p className="text-xs text-muted-foreground">
                    Needs an active AI provider —{" "}
                    <Link href="/settings/ai-provider" className="underline underline-offset-4">
                      configure one
                    </Link>
                    . The audit runs without it.
                  </p>
                )}
              </div>

              <p className="text-xs text-muted-foreground">
                This produces an automated technical assessment, not a compliance certification.
              </p>

              <div className="flex items-center justify-between border-t border-border pt-4">
                <Button variant="ghost" nativeButton={false} render={<Link href={backHref} />}>
                  Cancel
                </Button>
                <Button disabled={run.isPending} onClick={() => run.mutate()}>
                  <ShieldCheck />
                  {run.isPending ? "Starting…" : "Run audit"}
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

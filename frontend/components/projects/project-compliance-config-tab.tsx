"use client";

import { Bell, FileSearch, Save, ShieldCheck, Sliders } from "lucide-react";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/client";
import { listFrameworks } from "@/lib/api/compliance";
import { queryKeys } from "@/lib/api/query-keys";
import {
  getProjectPolicy,
  updateProjectPolicy,
  type ProjectPolicy,
} from "@/lib/api/workspace-settings";

interface ProjectComplianceConfigTabProps {
  projectId: string;
}

/** Tells the reader where a value actually came from, which is the whole point of an
 *  inherit-by-default policy model. */
function SourceBadge({ overridden }: { overridden: boolean }) {
  return (
    <Badge variant="outline" className="font-mono text-[10px] normal-case">
      {overridden ? "Overridden here" : "Inherited from workspace"}
    </Badge>
  );
}

export function ProjectComplianceConfigTab({ projectId }: ProjectComplianceConfigTabProps) {
  const queryClient = useQueryClient();

  // Driven by the real catalog endpoint rather than a hardcoded list. That endpoint returns only
  // the frameworks the evaluator will actually run (SOC 2 and ISO 27001 today), so this tab can
  // never advertise a framework an audit would refuse.
  const { data: catalog, isLoading: catalogLoading } = useQuery({
    queryKey: queryKeys.compliance.frameworks(),
    queryFn: listFrameworks,
  });
  const { data: policy, isLoading: policyLoading } = useQuery({
    queryKey: queryKeys.projects.policy(projectId),
    queryFn: () => getProjectPolicy(projectId),
  });
  const frameworks = catalog?.items ?? [];

  // Local editable copy, re-synced whenever the fetched policy changes.
  const [form, setForm] = useState<ProjectPolicy | null>(null);
  const [syncedFrom, setSyncedFrom] = useState<ProjectPolicy | null>(null);
  if (policy && policy !== syncedFrom) {
    setSyncedFrom(policy);
    setForm(policy);
  }

  const save = useMutation({
    mutationFn: (body: ProjectPolicy) =>
      updateProjectPolicy(projectId, {
        compliance_frameworks: body.compliance_frameworks,
        compliance_audit_scope: body.compliance_audit_scope,
        compliance_auto_audit_on_scan: body.compliance_auto_audit_on_scan,
        compliance_evidence_retention_days: body.compliance_evidence_retention_days,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.projects.policy(projectId), updated);
      toast.success("Compliance policy saved");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save policy"),
  });

  if (policyLoading || !form) return <Skeleton className="h-64 w-full" />;

  const canManage = form.can_manage;
  // null = inheriting. Toggling a framework starts an override seeded from what is currently
  // in effect, so the first click never silently discards the inherited selection.
  const selected = form.compliance_frameworks ?? form.effective_compliance_frameworks;

  function toggleFramework(key: string) {
    setForm((f) => {
      if (!f) return f;
      const current = f.compliance_frameworks ?? f.effective_compliance_frameworks;
      return {
        ...f,
        compliance_frameworks: current.includes(key)
          ? current.filter((k) => k !== key)
          : [...current, key],
      };
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border/60 pb-3">
        <div>
          <div className="flex items-center gap-2">
            <Sliders className="size-5 text-muted-foreground" />
            <h2 className="text-base font-semibold tracking-tight text-foreground">
              Compliance Governance &amp; Policy Configuration
            </h2>
            <Badge variant="outline" className="font-mono text-[10px]">
              Project Level
            </Badge>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">
            This project&apos;s compliance policy — what <span className="font-medium text-foreground">Run
            Audit</span> assesses, over which evidence, and how deep. Set it once here; the
            Compliance Audits tab then runs it in one click with no questions. Anything not set
            here is inherited from the workspace defaults in{" "}
            <Link href="/settings/general" className="underline underline-offset-4">
              Settings → General
            </Link>
            .
          </p>
        </div>

        {canManage && (
          <Button
            onClick={() => save.mutate(form)}
            size="sm"
            variant="outline"
            className="gap-1.5 font-medium shrink-0"
            disabled={save.isPending}
          >
            <Save className="size-3.5" />
            <span>{save.isPending ? "Saving…" : "Save Changes"}</span>
          </Button>
        )}
      </div>

      {!canManage && (
        <p className="text-xs text-muted-foreground">
          You need owner or admin access to change this policy. The values below are read-only.
        </p>
      )}

      {/* Target Frameworks */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono">
            Target Frameworks ({frameworks.length} supported)
          </h3>
          <SourceBadge overridden={form.compliance_frameworks !== null} />
        </div>
        <p className="text-xs text-muted-foreground">
          These are the frameworks whose control-to-evidence mapping has been reviewed control by
          control. Others are not offered rather than offered with mappings nobody has checked.
          What you pick here is exactly what an audit assesses — by hand or automatically.
          Selecting none falls back to every supported framework.
        </p>

        <div className="grid grid-cols-1 gap-3.5 md:grid-cols-2">
          {catalogLoading && <Skeleton className="h-32 w-full" />}
          {frameworks.map((framework) => {
            const manualOnly = framework.controls_total - framework.assessed_total;
            const isOn = selected.includes(framework.key);
            return (
              <Card
                key={framework.key}
                className={isOn ? "border-primary/40 bg-card/90" : "border-border/60 bg-card/50"}
              >
                <CardHeader className="p-4 pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-1 min-w-0">
                      <CardTitle className="text-sm font-semibold text-foreground">
                        {framework.title}
                      </CardTitle>
                      <p className="text-[11px] font-mono text-muted-foreground">
                        {framework.controls_total} controls · {framework.assessed_total} assessable
                        from code · {manualOnly} manual review
                      </p>
                    </div>
                    <Switch
                      checked={isOn}
                      disabled={!canManage}
                      onCheckedChange={() => toggleFramework(framework.key)}
                      aria-label={`Assess against ${framework.title}`}
                    />
                  </div>
                </CardHeader>
                <CardContent className="p-4 pt-2">
                  <p className="text-xs text-muted-foreground leading-relaxed">
                    {framework.scope_note}
                  </p>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>

      {/* Evidence scope + depth — the two questions the old three-step audit wizard asked
          at run time. Answered once here so Run Audit is a single click. */}
      <Card className="border-border/80 bg-card/60">
        <CardHeader className="p-4 pb-3 border-b border-border/60">
          <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono flex items-center gap-2">
            <FileSearch className="size-4 text-muted-foreground" />
            Evidence &amp; Depth
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4 space-y-5 text-xs">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Label className="font-medium text-foreground">
                Which findings count as evidence
              </Label>
              <SourceBadge overridden={form.compliance_audit_scope !== null} />
            </div>
            <div className="flex flex-wrap gap-4">
              {(
                [
                  ["latest", "Latest scan per repository"],
                  ["history", "All historical findings"],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="project-audit-scope"
                    className="size-3.5"
                    disabled={!canManage}
                    checked={form.effective_compliance_audit_scope === value}
                    onChange={() =>
                      setForm({
                        ...form,
                        compliance_audit_scope: value,
                        effective_compliance_audit_scope: value,
                      })
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {form.effective_compliance_audit_scope === "latest"
                ? "Current posture: only each repository's most recent completed scan. A finding you have since fixed stops counting against a control."
                : "Every finding ever ingested for this project, including ones from superseded scans that may already be fixed."}
            </p>
          </div>

          <div className="space-y-1.5 pt-2 border-t border-border/40">
            <Label className="font-medium text-foreground">AI explanations</Label>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {form.effective_compliance_audit_ai_narrative
                ? "On. Audits started by hand also write an explanation and a suggested fix for each failing control. Pass or fail is still computed from scan evidence — the AI can never move a verdict."
                : "Off. Audits report verdicts and evidence without written narrative."}{" "}
              This one authorises LLM spend, so it is workspace-wide and admin-owned — there is
              deliberately no project override.{" "}
              <Link href="/settings/general" className="underline underline-offset-4">
                Settings → General
              </Link>
              .
            </p>
          </div>

          <p className="text-[11px] text-muted-foreground pt-2 border-t border-border/40">
            Audits always cover every repository in the project. Scoping one audit to a subset
            of repositories is not configurable here.
          </p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Audit automation */}
        <Card className="border-border/80 bg-card/60">
          <CardHeader className="p-4 pb-3 border-b border-border/60">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono flex items-center gap-2">
              <ShieldCheck className="size-4 text-muted-foreground" />
              Automated Audit Policy
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 space-y-4 text-xs">
            <div className="flex items-center justify-between gap-3">
              <div className="space-y-0.5">
                <Label className="font-medium text-foreground">Continuous Posture Evaluation</Label>
                <p className="text-[11px] text-muted-foreground">
                  Run an audit whenever a scan of this project completes. Deterministic
                  evaluation only — no AI narrative, so this never spends on LLM calls.
                </p>
                <SourceBadge overridden={form.compliance_auto_audit_on_scan !== null} />
              </div>
              <Switch
                checked={form.effective_compliance_auto_audit_on_scan}
                disabled={!canManage}
                onCheckedChange={(checked) =>
                  setForm({
                    ...form,
                    compliance_auto_audit_on_scan: checked,
                    effective_compliance_auto_audit_on_scan: checked,
                  })
                }
              />
            </div>

            <div className="space-y-1.5 pt-2 border-t border-border/40">
              <Label className="font-medium text-foreground">
                Audit Evidence Retention (days)
              </Label>
              <Input
                type="number"
                min={1}
                max={3650}
                placeholder="Inherit"
                disabled={!canManage}
                value={form.compliance_evidence_retention_days ?? ""}
                onChange={(e) =>
                  setForm({
                    ...form,
                    compliance_evidence_retention_days: e.target.value
                      ? Number(e.target.value)
                      : null,
                  })
                }
                className="font-mono text-xs max-w-32 h-8"
              />
              <p className="text-[11px] text-muted-foreground">
                Completed audits older than this are deleted. Blank inherits the workspace
                setting, which is currently{" "}
                {form.effective_compliance_evidence_retention_days
                  ? `${form.effective_compliance_evidence_retention_days} days`
                  : "keep forever"}
                .
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Alerts */}
        <Card className="border-border/80 bg-card/60">
          <CardHeader className="p-4 pb-3 border-b border-border/60">
            <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground font-mono flex items-center gap-2">
              <Bell className="size-4 text-muted-foreground" />
              Drift &amp; Violation Alerts
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 space-y-3 text-xs">
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              Every member of this project can subscribe to{" "}
              <span className="font-medium text-foreground">Compliance audit completed</span> and{" "}
              <span className="font-medium text-foreground">Compliance controls failing</span>,
              in-app and by email. Subscriptions are per person rather than per project — one
              team member wanting an alert should not force it on everyone else.
            </p>
            <Link
              href="/settings/notifications"
              className="inline-block text-[11px] underline underline-offset-4"
            >
              Manage your notification preferences
            </Link>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, Map, ScanSearch, Settings, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { RequireRole } from "@/components/auth/require-role";
import { EmptyState } from "@/components/common/empty-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import { listFrameworks } from "@/lib/api/compliance";
import { queryKeys } from "@/lib/api/query-keys";
import {
  getWorkspaceSettings,
  updateWorkspaceSettings,
  type WorkspaceSettings,
} from "@/lib/api/workspace-settings";
import { useHasRole } from "@/lib/hooks/use-has-role";

/**
 * The settings scope map. Every configurable thing in the portal, with who owns it and
 * whether a project can override it — the answer to "is this global or per-project?", which
 * was previously only discoverable by opening each page and guessing.
 *
 * Hand-maintained. It is a documentation table, not derived state: deriving it would need
 * every setting to carry scope metadata for the sake of one read-only table.
 */
const SCOPE_MAP: { setting: string; scope: string; where: string; href?: string }[] = [
  { setting: "Scan analysers (secrets, SCA, framework checks)", scope: "Workspace → project override", where: "This page / Project → Settings" },
  { setting: "Compliance frameworks", scope: "Workspace → project override", where: "This page / Project → Compliance config" },
  { setting: "Audit evidence scope (latest vs all history)", scope: "Workspace → project override", where: "This page / Project → Compliance config" },
  { setting: "AI explanations in audits", scope: "Portal admin only (authorises LLM spend)", where: "This page" },
  { setting: "Automatic audit on scan", scope: "Workspace → project override", where: "This page / Project → Compliance config" },
  { setting: "Audit evidence retention", scope: "Workspace → project override", where: "This page / Project → Compliance config" },
  { setting: "Default report template", scope: "Workspace → project override", where: "Settings → Report Templates", href: "/settings/report-templates" },
  { setting: "AI provider (portal-wide or per-project BYOK)", scope: "Workspace, or per-project when BYOK is on", where: "Settings → AI Provider", href: "/settings/ai-provider" },
  { setting: "Auto-fix on/off, confidence threshold", scope: "Workspace → project may tighten", where: "Settings → Auto-fix", href: "/settings/auto-fix" },
  { setting: "Auto-fix allowance, blocking severities, quota grants", scope: "Portal admin only", where: "Settings → Auto-fix", href: "/settings/auto-fix" },
  { setting: "Notification subscriptions", scope: "Per user", where: "Settings → Notifications", href: "/settings/notifications" },
  { setting: "Repository credentials", scope: "Per user, copied per project connection", where: "Settings → Integrations", href: "/settings/integrations" },
];

function WorkspaceDefaultsCard() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.settings.workspace(),
    queryFn: getWorkspaceSettings,
  });
  const { data: catalog } = useQuery({
    queryKey: queryKeys.compliance.frameworks(),
    queryFn: listFrameworks,
  });

  // Local editable copy re-synced when the fetched data changes — same
  // adjust-state-during-render pattern as the Auto-Fix policy card.
  const [form, setForm] = useState<WorkspaceSettings | null>(null);
  const [syncedFrom, setSyncedFrom] = useState<WorkspaceSettings | null>(null);
  if (data && data !== syncedFrom) {
    setSyncedFrom(data);
    setForm(data);
  }

  const save = useMutation({
    mutationFn: (body: WorkspaceSettings) =>
      updateWorkspaceSettings({
        scan_enable_secrets: body.scan_enable_secrets,
        scan_enable_sca: body.scan_enable_sca,
        scan_enable_framework_checks: body.scan_enable_framework_checks,
        compliance_frameworks: body.compliance_frameworks,
        compliance_audit_scope: body.compliance_audit_scope,
        compliance_audit_ai_narrative: body.compliance_audit_ai_narrative,
        compliance_auto_audit_on_scan: body.compliance_auto_audit_on_scan,
        compliance_evidence_retention_days: body.compliance_evidence_retention_days,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.settings.workspace(), updated);
      toast.success("Workspace defaults saved");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save"),
  });

  if (isLoading || !form) return <p className="text-sm text-muted-foreground">Loading settings…</p>;

  const frameworks = catalog?.items ?? [];
  const toggleFramework = (key: string) =>
    setForm({
      ...form,
      compliance_frameworks: form.compliance_frameworks.includes(key)
        ? form.compliance_frameworks.filter((k) => k !== key)
        : [...form.compliance_frameworks, key],
    });

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ScanSearch className="size-4" /> Scan defaults
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Which analysers every cloud scan runs. A project can switch any of these off for
            itself on its Settings tab.
          </p>
          {(
            [
              ["scan_enable_secrets", "Secret detection", "Hardcoded credentials, tokens and keys."],
              ["scan_enable_sca", "Dependency scanning (SCA)", "Known-vulnerable packages in manifests and lockfiles."],
              ["scan_enable_framework_checks", "Framework checks", "Framework-specific misconfiguration rules."],
            ] as const
          ).map(([key, label, help]) => (
            <label key={key} className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-0.5 size-4"
                checked={form[key]}
                onChange={(e) => setForm({ ...form, [key]: e.target.checked })}
              />
              <span>
                <span className="block text-sm font-medium">{label}</span>
                <span className="block text-xs text-muted-foreground">{help}</span>
              </span>
            </label>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="size-4" /> Compliance defaults
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-2">
            <Label>Default frameworks</Label>
            <div className="flex flex-wrap gap-4">
              {frameworks.map((f) => (
                <label key={f.key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={form.compliance_frameworks.includes(f.key)}
                    onChange={() => toggleFramework(f.key)}
                  />
                  {f.title}
                </label>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              What Run Audit assesses, and what an automatic audit assesses. Only frameworks
              whose evidence mapping has been reviewed control by control are listed. Leave all
              unchecked to default to every supported framework.
            </p>
          </div>

          <div className="space-y-2">
            <Label>Evidence scope</Label>
            <div className="flex flex-wrap gap-4">
              {(
                [
                  ["latest", "Latest scan per repository"],
                  ["history", "All historical findings"],
                ] as const
              ).map(([value, label]) => (
                <label key={value} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name="compliance-audit-scope"
                    className="size-4"
                    checked={form.compliance_audit_scope === value}
                    onChange={() => setForm({ ...form, compliance_audit_scope: value })}
                  />
                  {label}
                </label>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              {form.compliance_audit_scope === "latest"
                ? "Current posture: only each repository's most recent completed scan, so a finding you have since fixed stops counting against a control."
                : "Every finding ever ingested, including ones from superseded scans that may already be fixed."}{" "}
              A project can pick the other scope for itself on its Compliance Config tab.
            </p>
          </div>

          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              className="mt-0.5 size-4"
              checked={form.compliance_audit_ai_narrative}
              onChange={(e) =>
                setForm({ ...form, compliance_audit_ai_narrative: e.target.checked })
              }
            />
            <span>
              <span className="block text-sm font-medium">
                Include AI explanations in audits started by hand
              </span>
              <span className="block text-xs text-muted-foreground">
                Pass or fail is always computed from scan evidence — the AI only writes the
                explanation and the suggested fix for controls that already failed. This
                authorises LLM spend, so there is no project-level override: it is on for the
                whole workspace or off. An audit still runs (without prose) if no AI provider
                is configured.
              </span>
            </span>
          </label>

          <label className="flex items-start gap-3">
            <input
              type="checkbox"
              className="mt-0.5 size-4"
              checked={form.compliance_auto_audit_on_scan}
              onChange={(e) =>
                setForm({ ...form, compliance_auto_audit_on_scan: e.target.checked })
              }
            />
            <span>
              <span className="block text-sm font-medium">Run an audit when a scan completes</span>
              <span className="block text-xs text-muted-foreground">
                Deterministic evaluation only — no AI narrative, so this never spends on LLM
                calls. Run an audit by hand when you want the written explanation.
              </span>
            </span>
          </label>

          <div className="space-y-2">
            <Label htmlFor="retention">Audit evidence retention (days)</Label>
            <Input
              id="retention"
              type="number"
              min={1}
              max={3650}
              className="max-w-32"
              placeholder="Forever"
              value={form.compliance_evidence_retention_days ?? ""}
              onChange={(e) =>
                setForm({
                  ...form,
                  compliance_evidence_retention_days: e.target.value
                    ? Number(e.target.value)
                    : null,
                })
              }
            />
            <p className="text-xs text-muted-foreground">
              Completed audits older than this are deleted. Leave blank to keep them
              indefinitely, which is the default.
            </p>
          </div>

          <Button onClick={() => save.mutate(form)} disabled={save.isPending}>
            {save.isPending ? "Saving…" : "Save defaults"}
          </Button>
        </CardContent>
      </Card>
    </>
  );
}

export default function GeneralSettingsPage() {
  const isAdmin = useHasRole("admin");

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold">General</h2>
        <p className="text-sm text-muted-foreground">
          Workspace-wide defaults. Projects inherit these unless they set their own.
        </p>
      </div>

      <RequireRole role="admin">
        <WorkspaceDefaultsCard />
      </RequireRole>
      {!isAdmin && (
        <EmptyState
          icon={Settings}
          title="Admins only"
          description="Only portal admins can change workspace defaults. Project-level overrides live on each project's Settings tab."
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Map className="size-4" /> Where each setting lives
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border/60 text-left">
                  <th className="py-2 pr-4 font-medium">Setting</th>
                  <th className="py-2 pr-4 font-medium">Scope</th>
                  <th className="py-2 font-medium">Where</th>
                </tr>
              </thead>
              <tbody>
                {SCOPE_MAP.map((row) => (
                  <tr key={row.setting} className="border-b border-border/30 align-top">
                    <td className="py-2 pr-4">{row.setting}</td>
                    <td className="py-2 pr-4 text-muted-foreground">
                      <Badge variant="outline" className="font-mono text-[10px] whitespace-nowrap">
                        {row.scope}
                      </Badge>
                    </td>
                    <td className="py-2 text-muted-foreground">
                      {row.href ? (
                        <Link href={row.href} className="underline underline-offset-4">
                          {row.where}
                        </Link>
                      ) : (
                        row.where
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 flex items-start gap-2 text-xs text-muted-foreground">
            <ClipboardList className="mt-0.5 size-3.5 shrink-0" />
            <span>
              A project override can only ever tighten workspace policy — a project may switch
              auto-fix off or raise its confidence bar, but cannot switch it on against a
              workspace-wide disable or lower the bar.
            </span>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

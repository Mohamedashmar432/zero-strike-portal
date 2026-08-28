"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import {
  getProjectPolicy,
  updateProjectPolicy,
  type ProjectPolicy,
} from "@/lib/api/workspace-settings";

/**
 * The scan and auto-fix half of this project's policy. Compliance policy has its own tab.
 *
 * Every control here is tri-state underneath: an override, or `null` meaning inherit. The UI
 * shows which of the two is in play rather than rendering a resolved value that looks like a
 * local decision — a setting you cannot tell the origin of is a setting you cannot reason about.
 */
export function ProjectPolicyCard({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.projects.policy(projectId),
    queryFn: () => getProjectPolicy(projectId),
  });

  const [form, setForm] = useState<ProjectPolicy | null>(null);
  const [syncedFrom, setSyncedFrom] = useState<ProjectPolicy | null>(null);
  if (data && data !== syncedFrom) {
    setSyncedFrom(data);
    setForm(data);
  }

  const save = useMutation({
    mutationFn: (body: ProjectPolicy) =>
      updateProjectPolicy(projectId, {
        scan_enable_secrets: body.scan_enable_secrets,
        scan_enable_sca: body.scan_enable_sca,
        scan_enable_framework_checks: body.scan_enable_framework_checks,
        auto_fix_enabled: body.auto_fix_enabled,
        auto_fix_confidence_threshold: body.auto_fix_confidence_threshold,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.projects.policy(projectId), updated);
      toast.success("Project policy saved");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save policy"),
  });

  if (isLoading || !form) return <Skeleton className="h-64 w-full" />;
  if (!form.can_manage) return null;

  const scanRows = [
    ["scan_enable_secrets", "effective_scan_enable_secrets", "Secret detection"],
    ["scan_enable_sca", "effective_scan_enable_sca", "Dependency scanning (SCA)"],
    ["scan_enable_framework_checks", "effective_scan_enable_framework_checks", "Framework checks"],
  ] as const;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">
          Scan &amp; Auto-Fix policy
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <p className="flex items-start gap-2 text-xs text-muted-foreground">
          <Info className="mt-0.5 size-3.5 shrink-0" />
          <span>
            Unset options inherit the workspace defaults in{" "}
            <Link href="/settings/general" className="underline underline-offset-4">
              Settings → General
            </Link>
            . A project can tighten policy but never loosen it — you can switch auto-fix off or
            raise its confidence bar, but not switch it on against a workspace-wide disable or
            lower the bar below it.
          </span>
        </p>

        <div className="space-y-3">
          <Label>Scan analysers</Label>
          {scanRows.map(([key, effectiveKey, label]) => (
            <div key={key} className="flex items-center justify-between gap-3">
              <label className="flex items-center gap-3 text-sm">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={form[effectiveKey]}
                  onChange={(e) =>
                    setForm({ ...form, [key]: e.target.checked, [effectiveKey]: e.target.checked })
                  }
                />
                {label}
              </label>
              <div className="flex items-center gap-2">
                <Badge variant="outline" className="font-mono text-[10px]">
                  {form[key] === null ? "Inherited" : "Overridden"}
                </Badge>
                {form[key] !== null && (
                  <button
                    type="button"
                    className="font-mono text-[10px] text-muted-foreground underline underline-offset-4 hover:text-foreground"
                    onClick={() => setForm({ ...form, [key]: null })}
                  >
                    reset
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>

        <div className="space-y-3 border-t border-border/40 pt-4">
          <div className="flex items-center justify-between gap-3">
            <label className="flex items-start gap-3">
              <input
                type="checkbox"
                className="mt-0.5 size-4"
                disabled={!form.workspace_auto_fix_enabled}
                checked={form.effective_auto_fix_enabled}
                onChange={(e) =>
                  setForm({
                    ...form,
                    auto_fix_enabled: e.target.checked,
                    effective_auto_fix_enabled: e.target.checked,
                  })
                }
              />
              <span>
                <span className="block text-sm font-medium">Auto-Fix enabled</span>
                <span className="block text-xs text-muted-foreground">
                  {form.workspace_auto_fix_enabled
                    ? "Switch off to disable AI Auto-Fix for this project only."
                    : "Auto-Fix is disabled workspace-wide, so it cannot be enabled here."}
                </span>
              </span>
            </label>
            <Badge variant="outline" className="font-mono text-[10px] shrink-0">
              {form.auto_fix_enabled === null ? "Inherited" : "Overridden"}
            </Badge>
          </div>

          <div className="space-y-2">
            <Label htmlFor="project-confidence">Confidence threshold (%)</Label>
            <Input
              id="project-confidence"
              type="number"
              min={form.workspace_auto_fix_confidence_threshold}
              max={100}
              className="max-w-32"
              placeholder={String(form.workspace_auto_fix_confidence_threshold)}
              value={form.auto_fix_confidence_threshold ?? ""}
              onChange={(e) =>
                setForm({
                  ...form,
                  auto_fix_confidence_threshold: e.target.value ? Number(e.target.value) : null,
                })
              }
            />
            <p className="text-xs text-muted-foreground">
              Blank inherits the workspace bar of{" "}
              {form.workspace_auto_fix_confidence_threshold}%. A lower number is ignored — the
              effective bar is the higher of the two, currently{" "}
              {form.effective_auto_fix_confidence_threshold}%.
            </p>
          </div>
        </div>

        <Button onClick={() => save.mutate(form)} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save policy"}
        </Button>
      </CardContent>
    </Card>
  );
}

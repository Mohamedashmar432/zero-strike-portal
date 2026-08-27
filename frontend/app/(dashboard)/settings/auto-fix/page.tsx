"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Settings2, ShieldCheck, Wand2, XCircle } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { RequireRole } from "@/components/auth/require-role";
import { EmptyState } from "@/components/common/empty-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getAiStatus } from "@/lib/api/ai";
import {
  getRemediationSettings,
  updateRemediationSettings,
  type RemediationSettings,
} from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { useHasRole } from "@/lib/hooks/use-has-role";

const SEVERITIES = ["critical", "high", "medium", "low", "info"] as const;

function AutoFixPolicyCard() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.ai.autofix.settings(),
    queryFn: getRemediationSettings,
  });

  // Local editable copy, seeded from the query and re-synced when the fetched data changes
  // (adjust-state-during-render pattern, same as the AI Provider dialog form).
  const [form, setForm] = useState<RemediationSettings | null>(null);
  const [syncedFrom, setSyncedFrom] = useState<RemediationSettings | null>(null);
  if (data && data !== syncedFrom) {
    setSyncedFrom(data);
    setForm(data);
  }

  const save = useMutation({
    mutationFn: (body: RemediationSettings) => updateRemediationSettings(body),
    onSuccess: (updated) => {
      queryClient.setQueryData(queryKeys.ai.autofix.settings(), updated);
      queryClient.invalidateQueries({ queryKey: queryKeys.ai.status() });
      toast.success("Auto-Fix settings saved");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save settings"),
  });

  if (isLoading || !form) {
    return <p className="text-sm text-muted-foreground">Loading settings…</p>;
  }

  const toggleSeverity = (sev: string) =>
    setForm((f) =>
      f
        ? {
            ...f,
            blocking_severities: f.blocking_severities.includes(sev)
              ? f.blocking_severities.filter((s) => s !== sev)
              : [...f.blocking_severities, sev],
          }
        : f
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Settings2 className="size-4" /> Policy
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5 size-4"
            checked={form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
          />
          <span>
            <span className="block text-sm font-medium">Auto-Fix enabled</span>
            <span className="block text-xs text-muted-foreground">
              When off, triggering a fix returns a “disabled by an administrator” error.
            </span>
          </span>
        </label>

        <div className="space-y-2">
          <Label htmlFor="confidence-threshold">Confidence threshold (%)</Label>
          <Input
            id="confidence-threshold"
            type="number"
            min={0}
            max={100}
            className="max-w-32"
            value={form.confidence_threshold}
            onChange={(e) => setForm({ ...form, confidence_threshold: Number(e.target.value) })}
          />
          <p className="text-xs text-muted-foreground">
            Fixes at or above this score surface as actionable; below it they’re flagged for manual
            review.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="max-findings">Max findings per job</Label>
          <Input
            id="max-findings"
            type="number"
            min={1}
            max={100}
            className="max-w-32"
            value={form.max_findings_per_job}
            onChange={(e) => setForm({ ...form, max_findings_per_job: Number(e.target.value) })}
          />
          <p className="text-xs text-muted-foreground">
            How many findings a single “Auto AI Fix” run will attempt.
          </p>
        </div>

        <div className="space-y-2">
          <Label htmlFor="per-scan-allowance">Auto-fix allowance per scan</Label>
          <Input
            id="per-scan-allowance"
            type="number"
            min={1}
            max={500}
            className="max-w-32"
            value={form.auto_fix_findings_per_scan}
            onChange={(e) =>
              setForm({ ...form, auto_fix_findings_per_scan: Number(e.target.value) })
            }
          />
          <p className="text-xs text-muted-foreground">
            Total distinct findings that may ever be auto-fixed on one scan. Separate from
            &ldquo;max findings per job&rdquo;, which caps a single run — a scan can be run
            through several. Each new scan of a repository starts a fresh allowance. Teams that
            need more on a specific scan request it, and you approve it under{" "}
            <span className="font-mono">Administration → Auto-Fix Requests</span>. Changing this
            number lifts every scan at once.
          </p>
        </div>

        <div className="space-y-2">
          <Label>Block a pull request when a fix introduces a new finding of</Label>
          <div className="flex flex-wrap gap-4">
            {SEVERITIES.map((sev) => (
              <label key={sev} className="flex items-center gap-2 text-sm capitalize">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={form.blocking_severities.includes(sev)}
                  onChange={() => toggleSeverity(sev)}
                />
                {sev}
              </label>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            After the patch is applied and re-scanned, the PR is withheld (marked for manual review)
            if it adds a new finding of any checked severity.
          </p>
        </div>

        <Button onClick={() => save.mutate(form)} disabled={save.isPending}>
          {save.isPending ? "Saving…" : "Save settings"}
        </Button>
      </CardContent>
    </Card>
  );
}

export default function AutoFixSettingsPage() {
  const isAdmin = useHasRole("admin");
  // Portal-level page, so no project scope. Must be wrapped, not passed bare: TanStack calls the
  // queryFn with its context object, which would arrive as the projectId argument.
  const { data: aiStatus } = useQuery({
    queryKey: queryKeys.ai.status(),
    queryFn: () => getAiStatus(),
  });
  const providerReady = aiStatus?.enabled ?? false;

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Auto-Fix</h2>
        <p className="text-sm text-muted-foreground">
          AI-generated, human-approved remediation for findings — reviewable diffs and one-click pull
          requests.
        </p>
      </div>

      <Alert className={providerReady ? "border-status-success/50 bg-status-success/5" : undefined}>
        {providerReady ? <CheckCircle2 className="text-status-success" /> : <XCircle />}
        <AlertTitle>{providerReady ? "AI is configured" : "AI provider not configured"}</AlertTitle>
        <AlertDescription>
          Auto-Fix needs an active, tool-capable AI provider (e.g. Anthropic or OpenAI).{" "}
          <Link href="/settings/ai-provider" className="underline underline-offset-4">
            Configure an AI provider
          </Link>
          . Local providers (LM Studio) can’t drive the fix agent.
        </AlertDescription>
      </Alert>

      <RequireRole role="admin">
        <AutoFixPolicyCard />
      </RequireRole>
      {!isAdmin && (
        <EmptyState
          icon={Settings2}
          title="Admins only"
          description="Only admins can change Auto-Fix policy."
        />
      )}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Wand2 className="size-4" /> How it works
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>
            Open a completed scan and click <strong>Auto AI Fix</strong> (or <strong>Generate Fix</strong> on a
            single finding). Proposals appear on the project’s <strong>Auto-Fix</strong> tab with a confidence
            score and a side-by-side diff.
          </p>
          <p>
            Only proposals with high confidence surface as actionable; the rest are flagged for manual review
            with a reason.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <ShieldCheck className="size-4" /> Safety
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2 text-sm text-muted-foreground">
          <p>The agent is read-only and never sees a repository token — it only proposes a patch.</p>
          <p>
            A pull request is opened only after an <strong>owner or admin</strong> explicitly approves, and only
            after the patch is re-scanned to confirm it clears the finding without introducing new ones.
            Nothing is auto-committed and nothing is auto-merged.
          </p>
          <p>Azure DevOps connections must be reconnected to grant write access before a PR can be opened.</p>
        </CardContent>
      </Card>
    </div>
  );
}

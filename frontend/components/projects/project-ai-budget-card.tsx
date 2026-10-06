"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { getProjectAiBudget, updateProjectAiBudget, type AiBudget } from "@/lib/api/ai";
import { queryKeys } from "@/lib/api/query-keys";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const num = new Intl.NumberFormat("en-US");

type Form = { usd: string; tokens: string; alert: string; hardStop: boolean };

function toForm(b: AiBudget): Form {
  return {
    usd: b.usd_monthly?.toString() ?? "",
    tokens: b.tokens_monthly?.toString() ?? "",
    alert: b.alert_percent.toString(),
    hardStop: b.hard_stop,
  };
}

export function ProjectAiBudgetCard({ projectId, canManage }: { projectId: string; canManage: boolean }) {
  const queryClient = useQueryClient();
  const budget = useQuery({
    queryKey: queryKeys.projects.aiBudget(projectId),
    queryFn: () => getProjectAiBudget(projectId),
  });
  const [form, setForm] = useState<Form | null>(null);
  // Seed once. Re-seeding on every new server copy would wipe half-typed edits on each refetch, and
  // React Query refetches on window focus -- so switching windows mid-edit used to lose the input.
  if (budget.data && form === null) setForm(toForm(budget.data));

  const save = useMutation({
    mutationFn: (f: Form) =>
      updateProjectAiBudget(projectId, {
        usd_monthly: f.usd.trim() ? Number(f.usd) : null,
        tokens_monthly: f.tokens.trim() ? Math.round(Number(f.tokens)) : null,
        alert_percent: Number(f.alert),
        hard_stop: f.hardStop,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.projects.aiBudget(projectId), data);
      setForm(toForm(data));
      toast.success("AI budget saved");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save the AI budget"),
  });

  const b = budget.data;
  const alertPct = Number(form?.alert) || 80;
  const invalid =
    !form ||
    (form.usd.trim() !== "" && !(Number(form.usd) > 0)) ||
    (form.tokens.trim() !== "" && !(Number(form.tokens) > 0)) ||
    !(alertPct >= 1 && alertPct <= 99);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">AI budget</CardTitle>
        <p className="text-sm text-muted-foreground">
          Monthly limits on this project&apos;s AI usage, counted from the 1st of each month (UTC). The project
          owner is emailed when usage crosses the alert threshold and again at the limit.
        </p>
      </CardHeader>
      <CardContent className="space-y-6">
        {!b || !form ? (
          <Skeleton className="h-24 w-full" />
        ) : (
          <>
            <div className="space-y-4">
              <Meter
                label="Spend this month"
                used={usd.format(b.used_usd)}
                limitText={b.usd_monthly ? usd.format(b.usd_monthly) : null}
                ratio={b.usd_monthly ? b.used_usd / b.usd_monthly : 0}
                alert={b.alert_percent}
              />
              <Meter
                label="Tokens this month"
                used={num.format(b.used_tokens)}
                limitText={b.tokens_monthly ? num.format(b.tokens_monthly) : null}
                ratio={b.tokens_monthly ? b.used_tokens / b.tokens_monthly : 0}
                alert={b.alert_percent}
              />
              <p className="text-xs text-muted-foreground">
                {num.format(b.requests)} AI {b.requests === 1 ? "call" : "calls"} this month.
                {b.unpriced_requests > 0 && (
                  <>
                    {" "}
                    <span className="text-severity-medium">
                      {num.format(b.unpriced_requests)} had no known price, so their cost is missing from the spend
                      above.
                    </span>{" "}
                    Set custom pricing on the provider to include them.
                  </>
                )}
              </p>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="budget-usd">Monthly spend limit (USD)</Label>
                <Input
                  id="budget-usd"
                  type="number"
                  min={0}
                  step="any"
                  placeholder="No limit"
                  value={form.usd}
                  disabled={!canManage}
                  onChange={(e) => setForm({ ...form, usd: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-tokens">Monthly token limit</Label>
                <Input
                  id="budget-tokens"
                  type="number"
                  min={0}
                  step={1000}
                  placeholder="No limit"
                  value={form.tokens}
                  disabled={!canManage}
                  onChange={(e) => setForm({ ...form, tokens: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="budget-alert">Alert at (% of limit)</Label>
                <Input
                  id="budget-alert"
                  type="number"
                  min={1}
                  max={99}
                  value={form.alert}
                  disabled={!canManage}
                  onChange={(e) => setForm({ ...form, alert: e.target.value })}
                />
              </div>
            </div>

            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm font-medium">Pause AI when a limit is reached</p>
                <p className="text-xs text-muted-foreground">
                  Off: alerts only, AI keeps running. On: AI analysis, auto-fix and compliance narratives are refused
                  for the rest of the month. Spend can pass the limit by up to one call.
                </p>
              </div>
              <Switch
                checked={form.hardStop}
                disabled={!canManage}
                onCheckedChange={(hardStop) => setForm({ ...form, hardStop })}
                aria-label="Pause AI when a limit is reached"
              />
            </div>

            {canManage ? (
              <Button onClick={() => save.mutate(form)} disabled={save.isPending || invalid}>
                {save.isPending ? "Saving…" : "Save budget"}
              </Button>
            ) : (
              <p className="text-xs text-muted-foreground">Only a project owner or admin can change the budget.</p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

/** Month-to-date usage against one limit. Amber past the alert threshold, red at the limit. */
function Meter({
  label,
  used,
  limitText,
  ratio,
  alert,
}: {
  label: string;
  used: string;
  limitText: string | null;
  ratio: number;
  alert: number;
}) {
  const pct = Math.round(ratio * 100);
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span>{label}</span>
        <span className="font-mono text-xs text-muted-foreground">
          {used}
          {limitText ? ` of ${limitText} (${pct}%)` : " · no limit"}
        </span>
      </div>
      {limitText && (
        <div
          className="h-1.5 overflow-hidden rounded-full bg-muted"
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.min(pct, 100)}
        >
          <div
            className={cn(
              "h-full rounded-full transition-[width]",
              pct >= 100 ? "bg-destructive" : pct >= alert ? "bg-severity-medium" : "bg-signal"
            )}
            style={{ width: `${Math.min(pct, 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}

"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pencil } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError } from "@/lib/api/client";
import { quotaTone, setCloudScanLimit } from "@/lib/api/project-insights";
import type { CloudScanQuota } from "@/lib/api/projects";
import { queryKeys } from "@/lib/api/query-keys";
import { cn, parseApiDate } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";

const TONE_TEXT = {
  ok: "text-muted-foreground",
  warn: "text-severity-medium",
  full: "text-severity-critical",
} as const;

const TONE_BAR = {
  ok: "bg-muted-foreground/50",
  warn: "bg-severity-medium",
  full: "bg-severity-critical",
} as const;

/** "Resets Nov 1 (UTC)" — the quota rolls over on the first of the UTC month. */
function resetsLabel(quota: CloudScanQuota): string {
  const d = parseApiDate(quota.resets_at);
  return `Resets ${d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })} (UTC)`;
}

/**
 * Inline limit editor — shared by the project header pill and the Control Panel Projects table.
 * The API (`PUT /admin/projects/{id}/cloud-scan-limit`) is admin-only; callers only render this for admins.
 */
export function CloudScanLimitEditor({
  projectId,
  quota,
  onDone,
}: {
  projectId: string;
  quota: CloudScanQuota;
  onDone: () => void;
}) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState(String(quota.limit));
  const parsed = Number(value);
  const valid = value.trim() !== "" && Number.isInteger(parsed) && parsed >= 0 && parsed <= 10000;

  const save = useMutation({
    mutationFn: (limit: number | null) => setCloudScanLimit(projectId, limit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.detail(projectId) });
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.all() });
      queryClient.invalidateQueries({ queryKey: ["admin", "project-insights"] });
      toast.success("Cloud scan limit updated");
      onDone();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update cloud scan limit"),
  });

  return (
    <form
      className="flex flex-wrap items-center gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        if (valid) save.mutate(parsed);
      }}
    >
      <Input
        type="number"
        min={0}
        max={10000}
        step={1}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        aria-label="Monthly cloud scan limit"
        className="h-7 w-20 font-mono text-xs"
        autoFocus
      />
      <Button type="submit" size="xs" disabled={!valid || save.isPending}>
        Save
      </Button>
      <Button
        type="button"
        size="xs"
        variant="outline"
        disabled={save.isPending || quota.is_default}
        onClick={() => save.mutate(null)}
      >
        Reset to default
      </Button>
      <Button type="button" size="xs" variant="ghost" onClick={onDone} disabled={save.isPending}>
        Cancel
      </Button>
      {!valid && <span className="text-[11px] text-destructive">Whole number, 0 to 10000 (0 pauses cloud scans).</span>}
    </form>
  );
}

/** Right-aligned header pill: `CLOUD SCANS 12 / 30`, a thin progress bar, reset date in the tooltip. */
export function CloudScanQuotaPill({
  projectId,
  quota,
}: {
  projectId: string;
  quota: CloudScanQuota | null | undefined;
}) {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [editing, setEditing] = useState(false);
  if (!quota) return null;

  const tone = quotaTone(quota);
  const pct = quota.limit > 0 ? Math.min(100, (100 * quota.used) / quota.limit) : 100;
  const title = `${resetsLabel(quota)}${quota.is_default ? " · workspace default limit" : " · project limit"}`;

  if (editing) {
    return <CloudScanLimitEditor projectId={projectId} quota={quota} onDone={() => setEditing(false)} />;
  }

  return (
    <div className="flex shrink-0 items-center gap-1.5" title={title}>
      <div
        className={cn(
          "min-w-32 rounded-sm border border-border px-2 py-1",
          tone === "full" && "border-severity-critical/60"
        )}
      >
        <div className="flex items-baseline justify-between gap-3 font-mono text-[10px] uppercase">
          <span className="text-muted-foreground">Cloud scans</span>
          <span className={cn("font-semibold tabular-nums", TONE_TEXT[tone])}>
            {quota.used} / {quota.limit}
          </span>
        </div>
        <div
          role="progressbar"
          aria-label="Cloud scans used this month"
          aria-valuemin={0}
          aria-valuemax={quota.limit}
          aria-valuenow={quota.used}
          className="mt-1 h-0.5 w-full overflow-hidden rounded-full bg-muted"
        >
          <div className={cn("h-full", TONE_BAR[tone])} style={{ width: `${pct}%` }} />
        </div>
      </div>
      {isAdmin && (
        <Button
          type="button"
          variant="ghost"
          size="icon-xs"
          aria-label="Edit monthly cloud scan limit"
          onClick={() => setEditing(true)}
        >
          <Pencil />
        </Button>
      )}
    </div>
  );
}

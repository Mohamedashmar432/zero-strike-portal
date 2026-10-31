"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Send } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { SectionRule } from "@/components/layout/section-rule";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/client";
import {
  getDigestPreview,
  getDigestSettings,
  saveDigestSettings,
  sendDigestTest,
  type DigestSettings,
} from "@/lib/api/digest";
import { queryKeys } from "@/lib/api/query-keys";
import { listWebhookChannels } from "@/lib/api/webhook-channels";
import { when } from "./date-range";
import { DigestPreviewTable } from "./digest-preview";
import { ProjectPicker } from "./project-picker";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const pad = (n: number) => String(n).padStart(2, "0");

// The schedule is stored in UTC but an admin thinks in their own clock. Converting through a fixed
// reference week (Sun 2024-01-07) also carries the weekday across midnight. Backend weekday: 0 = Monday.
const REF_SUNDAY_DAY = 7;
const jsDay = (backendWeekday: number) => (backendWeekday + 1) % 7;
const backendDay = (js: number) => (js + 6) % 7;

export function utcToLocal(weekday: number, hourUtc: number, minuteUtc: number) {
  const d = new Date(Date.UTC(2024, 0, REF_SUNDAY_DAY + jsDay(weekday), hourUtc, minuteUtc));
  return { weekday: backendDay(d.getDay()), time: `${pad(d.getHours())}:${pad(d.getMinutes())}` };
}

export function localToUtc(weekday: number, time: string) {
  const [h, m] = time.split(":").map(Number);
  const d = new Date(2024, 0, REF_SUNDAY_DAY + jsDay(weekday), h || 0, m || 0);
  return { weekday: backendDay(d.getUTCDay()), hour_utc: d.getUTCHours(), minute_utc: d.getUTCMinutes() };
}

const tzName = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

function DigestForm({
  settings,
  projects,
}: {
  settings: DigestSettings;
  projects: { project_id: string; name: string }[];
}) {
  const queryClient = useQueryClient();
  const initial = utcToLocal(settings.weekday, settings.hour_utc, settings.minute_utc);
  const [enabled, setEnabled] = useState(settings.enabled);
  const [frequency, setFrequency] = useState(settings.frequency);
  const [time, setTime] = useState(initial.time);
  const [weekday, setWeekday] = useState(initial.weekday);
  const [projectIds, setProjectIds] = useState(settings.project_ids);
  const [stale, setStale] = useState(settings.include_stale_projects);
  const [showPreview, setShowPreview] = useState(false);
  const [confirmSend, setConfirmSend] = useState(false);

  const save = useMutation({
    mutationFn: () => {
      const utc = localToUtc(weekday, time);
      return saveDigestSettings({
        enabled,
        frequency,
        hour_utc: utc.hour_utc,
        minute_utc: utc.minute_utc,
        weekday: frequency === "weekly" ? utc.weekday : settings.weekday,
        project_ids: projectIds,
        include_stale_projects: stale,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.digestSettings() });
      toast.success("Digest settings saved");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save digest settings"),
  });

  const preview = useQuery({
    queryKey: queryKeys.admin.digestPreview(),
    queryFn: getDigestPreview,
    enabled: showPreview,
    staleTime: 0,
  });

  const channels = useQuery({ queryKey: queryKeys.admin.webhookChannels(), queryFn: listWebhookChannels });
  const noDigestChannel = channels.data !== undefined && !channels.data.some((c) => c.enabled && c.include_digest);

  const sendTest = useMutation({
    mutationFn: sendDigestTest,
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.webhookChannels() });
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.digestSettings() });
      setConfirmSend(false);
      // Zero channels is not a success: the API answers 200 with sent=0 when no enabled channel
      // has "Include scheduled digest" on, and a green toast there reads as a Teams delivery.
      if (r.errors.length === 0 && r.sent === 0)
        toast.error("Nothing was sent. No enabled webhook channel has “Include scheduled digest” switched on.");
      else if (r.errors.length === 0)
        toast.success(`Digest sent to ${r.sent} channel${r.sent === 1 ? "" : "s"}, ${r.cards} cards each`);
      else
        toast.error(
          `Sent to ${r.sent}, failed for ${r.errors.map((e) => `${e.name}: ${e.error}`).join("; ")}`
        );
    },
    onError: (err) => {
      setConfirmSend(false);
      toast.error(err instanceof ApiError ? err.message : "Failed to send the digest");
    },
  });

  return (
    <div className="space-y-4">
      <div className="space-y-4 rounded-lg border border-border p-4">
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="digest-enabled">Send the scheduled digest</Label>
          <Switch id="digest-enabled" checked={enabled} onCheckedChange={setEnabled} aria-label="Digest enabled" />
        </div>
        {noDigestChannel && (
          <p role="alert" className="text-xs text-severity-critical">
            No enabled webhook channel includes the digest, so nothing will be posted to Teams. Edit a channel
            below and switch on “Include scheduled digest”.
          </p>
        )}

        <div className="flex flex-wrap items-end gap-4">
          <div className="space-y-1.5">
            <Label>Frequency</Label>
            <div className="flex gap-1 rounded-lg border border-border p-0.5">
              {(["daily", "weekly"] as const).map((f) => (
                <Button
                  key={f}
                  size="sm"
                  variant={frequency === f ? "secondary" : "ghost"}
                  aria-pressed={frequency === f}
                  onClick={() => setFrequency(f)}
                >
                  {f === "daily" ? "Daily" : "Weekly"}
                </Button>
              ))}
            </div>
          </div>
          {frequency === "weekly" && (
            <div className="space-y-1.5">
              <Label>Day</Label>
              <div className="flex flex-wrap gap-1 rounded-lg border border-border p-0.5">
                {WEEKDAYS.map((d, i) => (
                  <Button
                    key={d}
                    size="sm"
                    variant={weekday === i ? "secondary" : "ghost"}
                    aria-pressed={weekday === i}
                    onClick={() => setWeekday(i)}
                  >
                    {d.slice(0, 3)}
                  </Button>
                ))}
              </div>
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="digest-time">Time ({tzName()})</Label>
            <Input id="digest-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} className="w-32" />
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Shown in your local time; stored as UTC
          {time && ` (${pad(localToUtc(weekday, time).hour_utc)}:${pad(localToUtc(weekday, time).minute_utc)} UTC)`}.
        </p>

        <div className="space-y-2">
          <Label>Projects in the digest</Label>
          <ProjectPicker projects={projects} value={projectIds} onChange={setProjectIds} />
        </div>

        <label className="flex items-center justify-between gap-3 text-sm">
          <span>
            List stale projects
            <span className="block text-xs text-muted-foreground">Projects with no scan in the last 30 days.</span>
          </span>
          <Switch checked={stale} onCheckedChange={setStale} aria-label="List stale projects" />
        </label>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-3">
          <p className="text-xs text-muted-foreground">
            {settings.last_sent_at ? (
              <>
                Last sent {when(settings.last_sent_at)} —{" "}
                <span className={settings.last_status === "ok" || settings.last_status === "sent" ? "" : "text-severity-critical"}>
                  {settings.last_status ?? "unknown"}
                </span>
                {settings.last_error ? `: ${settings.last_error}` : ""}
              </>
            ) : (
              "Never sent."
            )}
          </p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setShowPreview(true)}>
              <Eye /> Preview
            </Button>
            <Button variant="outline" size="sm" onClick={() => setConfirmSend(true)}>
              <Send /> Send test now
            </Button>
            <Button size="sm" disabled={save.isPending || !time} onClick={() => save.mutate()}>
              {save.isPending ? "Saving…" : "Save settings"}
            </Button>
          </div>
        </div>
      </div>

      {showPreview && (
        <DigestPreviewTable
          preview={preview.data}
          isLoading={preview.isLoading || preview.isFetching}
          isError={preview.isError}
          onRefresh={() => preview.refetch()}
        />
      )}

      <ConfirmDialog
        open={confirmSend}
        onOpenChange={setConfirmSend}
        title="Send the digest now?"
        description="This posts the current digest to every enabled channel that includes the digest — real Teams channels, not a sandbox. It arrives as several cards: scanner health, project status (10 per card), then a dated summary."
        confirmLabel="Send to Teams"
        pendingLabel="Sending…"
        pending={sendTest.isPending}
        destructive={false}
        onConfirm={() => sendTest.mutate()}
      />
    </div>
  );
}

export function DigestSection({ projects }: { projects: { project_id: string; name: string }[] }) {
  const settings = useQuery({ queryKey: queryKeys.admin.digestSettings(), queryFn: getDigestSettings });
  return (
    <div className="space-y-3">
      <SectionRule label="Digest" />
      {settings.isLoading && <p className="text-sm text-muted-foreground">Loading digest settings…</p>}
      {settings.isError && <p className="text-sm text-destructive">Failed to load digest settings.</p>}
      {/* Keyed on the saved values so the form re-seeds after a save instead of drifting from the server. */}
      {settings.data && <DigestForm key={JSON.stringify(settings.data)} settings={settings.data} projects={projects} />}
    </div>
  );
}

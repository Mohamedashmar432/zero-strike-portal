"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, RefreshCw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { DeliveryChips } from "@/components/alerts/delivery-chips";
import { SectionRule } from "@/components/layout/section-rule";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api/client";
import {
  getLiveAlertStatus,
  runLiveAlertCheck,
  saveLiveAlertSettings,
  type LiveAlertMinSeverity,
  type LiveAlertStatus,
  type RunPreview,
} from "@/lib/api/live-alerts";
import { queryKeys } from "@/lib/api/query-keys";
import { RelativeTime } from "@/components/common/relative-time";
import { cardPreview, formatBytes, lagLabel, POLICY_LABEL } from "@/lib/live-alerts";
import { when } from "./date-range";

const MIN_OPTIONS: LiveAlertMinSeverity[] = ["critical", "high", "medium"];

function FeedStatus({ s }: { s: LiveAlertStatus }) {
  if (s.failing_since)
    return (
      <p role="alert" className="text-sm text-severity-critical">
        OSV feed unreachable since {when(s.failing_since)}
        {s.last_error ? `: ${s.last_error}` : "."}
      </p>
    );
  if (!s.last_success_at)
    return (
      <p className="text-sm text-muted-foreground">
        No check has completed yet.{s.last_error ? ` Last error: ${s.last_error}` : ""}
      </p>
    );
  return (
    <p className="text-sm text-muted-foreground">
      Last check <RelativeTime iso={s.last_success_at} />, OSV feed live
      {s.last_status === "partial" && s.last_error ? ` (partial: ${s.last_error})` : ""}.
    </p>
  );
}

function PreviewList({ previews }: { previews: RunPreview[] }) {
  if (previews.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        Nothing to send: no new advisory matches a project inventory right now.
      </p>
    );
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Preview only. Nothing was sent and no feed position moved.
      </p>
      {previews.map((p, i) => {
        const c = cardPreview(p.card);
        return (
          <div key={`${p.project_id}-${i}`} className="space-y-1 rounded-lg border border-border p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium">{p.project_name}</p>
              <span className="font-mono text-xs text-muted-foreground">{formatBytes(p.bytes)}</span>
            </div>
            <p className="text-sm">{c.title}</p>
            {c.text && <p className="text-xs text-muted-foreground">{c.text}</p>}
            {c.facts.length > 0 && (
              <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-0.5 text-xs">
                {c.facts.map((f, j) => (
                  <div key={j} className="contents">
                    <dt className="text-muted-foreground">{f.title}</dt>
                    <dd className="break-words">{f.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        );
      })}
    </div>
  );
}

function LiveAlertsBody({ s }: { s: LiveAlertStatus }) {
  const queryClient = useQueryClient();
  const [previews, setPreviews] = useState<RunPreview[] | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.admin.liveAlerts() });

  const save = useMutation({
    mutationFn: saveLiveAlertSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.admin.liveAlerts(), data);
      toast.success("Live alert settings saved");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save live alert settings"),
  });

  const check = useMutation({
    mutationFn: () => runLiveAlertCheck(false),
    onSuccess: (r) => {
      refresh();
      if (r.status === "skipped") toast.message("Check skipped");
      else toast.success("Check finished");
    },
    onError: (err) => {
      refresh();
      toast.error(
        err instanceof ApiError && err.status === 409
          ? "A check is already running"
          : err instanceof ApiError
            ? err.message
            : "The check failed"
      );
    },
  });

  const preview = useMutation({
    mutationFn: () => runLiveAlertCheck(true),
    onSuccess: (r) => setPreviews(r.previews),
    onError: (err) =>
      toast.error(
        err instanceof ApiError && err.status === 409
          ? "A check is already running"
          : err instanceof ApiError
            ? err.message
            : "The preview failed"
      ),
  });

  const c = s.coverage;
  const busy = save.isPending;

  return (
    <div className="space-y-4">
      {!s.server_watch_enabled && (
        <p role="alert" className="rounded-lg border border-severity-critical p-3 text-sm font-medium text-severity-critical">
          Disabled by the server (ADVISORY_WATCH_ENABLED=false)
        </p>
      )}
      {!s.email_delivery_configured && (
        <p className="text-xs text-muted-foreground">Email is not configured on this portal; email copies are not sent.</p>
      )}

      <div className="space-y-4 rounded-lg border border-border p-4">
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="live-alerts-enabled">Alert on new dependency advisories</Label>
          <Switch
            id="live-alerts-enabled"
            checked={s.enabled}
            disabled={busy}
            onCheckedChange={(enabled) => save.mutate({ enabled })}
            aria-label="Live dependency alerts enabled"
          />
        </div>
        <p className="text-xs text-muted-foreground">
          Sent to each project&apos;s own alert webhook and mailboxes, to webhook channels subscribed to New dependency
          advisory, and to members per their notification settings.
        </p>

        <div className="space-y-1.5">
          <Label htmlFor="live-alerts-min">Minimum severity</Label>
          <Select
            value={s.min_severity}
            onValueChange={(v) => v && save.mutate({ min_severity: v as LiveAlertMinSeverity })}
            disabled={busy}
          >
            <SelectTrigger id="live-alerts-min" className="w-56" aria-label="Minimum severity">
              <SelectValue>{POLICY_LABEL[s.min_severity]}</SelectValue>
            </SelectTrigger>
            <SelectContent>
              {MIN_OPTIONS.map((v) => (
                <SelectItem key={v} value={v}>
                  {POLICY_LABEL[v]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <label className="flex items-center justify-between gap-3 text-sm">
          <span>
            Include malicious-package reports
            <span className="block text-xs text-muted-foreground">
              Reports from the OSV malicious-packages feed, alongside vulnerability advisories.
            </span>
          </span>
          <Switch
            checked={s.include_malicious}
            disabled={busy}
            onCheckedChange={(include_malicious) => save.mutate({ include_malicious })}
            aria-label="Include malicious-package reports"
          />
        </label>

        <div className="space-y-2 border-t border-border pt-3">
          <FeedStatus s={s} />
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="max-w-xl text-xs text-muted-foreground">
              Check now runs the real check and delivers real alerts to subscribed channels and project webhooks for
              any genuinely new advisory. Preview never sends anything.
            </p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={preview.isPending} onClick={() => preview.mutate()}>
                <Eye /> {preview.isPending ? "Reading…" : "Preview"}
              </Button>
              <Button size="sm" disabled={check.isPending} onClick={() => check.mutate()}>
                <RefreshCw /> {check.isPending ? "Checking…" : "Check now and send alerts"}
              </Button>
            </div>
          </div>
        </div>
      </div>

      {previews && <PreviewList previews={previews} />}

      <div className="space-y-2">
        <Label>Feed position by ecosystem</Label>
        {s.ecosystems.length === 0 ? (
          <p className="text-sm text-muted-foreground">No ecosystems are tracked yet.</p>
        ) : (
          <div className="overflow-hidden rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 text-xs">
                  <TableHead className="py-2.5">Ecosystem</TableHead>
                  <TableHead className="py-2.5">Feed read up to</TableHead>
                  <TableHead className="py-2.5 text-right">Lag</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.ecosystems.map((e) => (
                  <TableRow key={e.ecosystem}>
                    <TableCell className="font-mono text-xs">{e.ecosystem}</TableCell>
                    <TableCell className="text-xs">
                      {e.cursor ? when(e.cursor) : "Starts on the next check, no history is back-filled"}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">{lagLabel(e.lag_minutes)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>

      <div className="space-y-1">
        <p className="text-sm">
          {c.projects_with_inventory} of {c.projects_active} active projects have a dependency inventory
          <span className="text-muted-foreground">
            {" "}
            ({c.inventories_cloud} from cloud scans, {c.inventories_cicd} from CI
            {c.oldest_inventory_at ? `; oldest ${when(c.oldest_inventory_at)}` : ""}).
          </span>
        </p>
        <p className="text-xs text-muted-foreground">
          A project gets an inventory on its next scan once the scanner is on the new version.
        </p>
      </div>

      <div className="space-y-2">
        <Label>Recent alerts</Label>
        {s.recent.length === 0 ? (
          <p className="text-sm text-muted-foreground">No live alerts have been raised yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 text-xs">
                  <TableHead className="py-2.5">Project</TableHead>
                  <TableHead className="py-2.5">Advisory</TableHead>
                  <TableHead className="py-2.5">Package</TableHead>
                  <TableHead className="py-2.5">Severity</TableHead>
                  <TableHead className="py-2.5">Released</TableHead>
                  <TableHead className="py-2.5">Delivery</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {s.recent.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="text-xs">{r.project_name ?? "Deleted project"}</TableCell>
                    <TableCell className="font-mono text-xs">{r.advisory_id}</TableCell>
                    <TableCell className="font-mono text-xs">
                      {r.package}@{r.version}
                    </TableCell>
                    <TableCell>
                      <SeverityBadge severity={r.severity} />
                    </TableCell>
                    <TableCell className="text-xs">
                      <RelativeTime iso={r.published_at} />
                    </TableCell>
                    <TableCell>
                      <DeliveryChips delivery={r.delivery} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </div>
    </div>
  );
}

export function LiveAlertsSection() {
  const status = useQuery({ queryKey: queryKeys.admin.liveAlerts(), queryFn: getLiveAlertStatus });
  return (
    <div className="space-y-3">
      <SectionRule label="Live dependency alerts" />
      {status.isLoading && <p className="text-sm text-muted-foreground">Loading live alert status…</p>}
      {status.isError && <p className="text-sm text-destructive">Failed to load live alert status.</p>}
      {status.data && <LiveAlertsBody s={status.data} />}
    </div>
  );
}

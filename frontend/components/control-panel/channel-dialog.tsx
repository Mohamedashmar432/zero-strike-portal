"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import {
  createWebhookChannel,
  updateWebhookChannel,
  type WebhookChannel,
  type WebhookEvent,
} from "@/lib/api/webhook-channels";
import { ProjectPicker } from "./project-picker";

function ChannelForm({
  channel,
  events,
  projects,
  onClose,
}: {
  channel: WebhookChannel | null;
  events: WebhookEvent[];
  projects: { project_id: string; name: string }[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(channel?.name ?? "");
  const [url, setUrl] = useState("");
  const [enabled, setEnabled] = useState(channel?.enabled ?? true);
  const [selected, setSelected] = useState<string[]>(channel?.events ?? []);
  const [projectIds, setProjectIds] = useState<string[]>(channel?.project_ids ?? []);
  const [includeDigest, setIncludeDigest] = useState(channel?.include_digest ?? false);

  const groups = new Map<string, WebhookEvent[]>();
  for (const e of events) groups.set(e.group, [...(groups.get(e.group) ?? []), e]);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        enabled,
        events: selected,
        project_ids: projectIds,
        include_digest: includeDigest,
      };
      // The stored URL is never returned, so blank on edit means "keep it".
      return channel
        ? updateWebhookChannel(channel.id, url.trim() ? { ...body, url: url.trim() } : body)
        : createWebhookChannel({ ...body, url: url.trim() });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.webhookChannels() });
      toast.success(channel ? "Channel updated" : "Channel added");
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to save the channel"),
  });

  const toggleEvent = (key: string) =>
    setSelected((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));
  const valid = name.trim().length > 0 && (channel !== null || url.trim().length > 0);

  return (
    <>
      <DialogHeader>
        <DialogTitle>{channel ? "Edit webhook channel" : "Add webhook channel"}</DialogTitle>
        <DialogDescription>
          A Teams (or compatible) incoming webhook. Each channel receives only the alerts ticked below.
        </DialogDescription>
      </DialogHeader>

      <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
        <div className="space-y-1.5">
          <Label htmlFor="wh-name">Name</Label>
          <Input id="wh-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="thinkshield-incidents" />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="wh-url">Webhook URL</Label>
          <Input
            id="wh-url"
            type="password"
            autoComplete="off"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={channel ? `Leave blank to keep the current URL (${channel.url_host})` : "https://…"}
          />
          <p className="text-xs text-muted-foreground">Stored encrypted and never shown again.</p>
        </div>
        <div className="flex items-center justify-between gap-3">
          <Label htmlFor="wh-enabled">Enabled</Label>
          <Switch id="wh-enabled" checked={enabled} onCheckedChange={setEnabled} aria-label="Enabled" />
        </div>

        <div className="space-y-2">
          <Label>Alerts</Label>
          {[...groups.entries()].map(([group, items]) => (
            <fieldset key={group} className="space-y-1 rounded-lg border border-border p-2.5">
              <legend className="legend px-1 text-muted-foreground">{group}</legend>
              {items.map((e) => (
                <label key={e.key} className="flex items-start gap-2 text-sm" title={e.description}>
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4"
                    checked={selected.includes(e.key)}
                    onChange={() => toggleEvent(e.key)}
                  />
                  <span>
                    {e.label}
                    <span className="block text-xs text-muted-foreground">{e.description}</span>
                  </span>
                </label>
              ))}
            </fieldset>
          ))}
        </div>

        <div className="space-y-2">
          <Label>Projects</Label>
          <ProjectPicker projects={projects} value={projectIds} onChange={setProjectIds} />
        </div>

        <label className="flex items-center justify-between gap-3 text-sm">
          <span>
            Include scheduled digest
            <span className="block text-xs text-muted-foreground">Also receives the daily or weekly summary card.</span>
          </span>
          <Switch checked={includeDigest} onCheckedChange={setIncludeDigest} aria-label="Include scheduled digest" />
        </label>
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          Cancel
        </Button>
        <Button disabled={!valid || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : channel ? "Save changes" : "Add channel"}
        </Button>
      </DialogFooter>
    </>
  );
}

/** `channel === null` adds a new one. The form mounts only while open so it always starts fresh. */
export function ChannelDialog({
  open,
  onOpenChange,
  channel,
  events,
  projects,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  channel: WebhookChannel | null;
  events: WebhookEvent[];
  projects: { project_id: string; name: string }[];
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        {open && (
          <ChannelForm
            channel={channel}
            events={events}
            projects={projects}
            onClose={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

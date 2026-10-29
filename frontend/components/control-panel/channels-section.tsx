"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Send, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { SectionRule } from "@/components/layout/section-rule";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import {
  deleteWebhookChannel,
  listWebhookChannels,
  listWebhookEvents,
  testWebhookChannel,
  type WebhookChannel,
} from "@/lib/api/webhook-channels";
import { cn } from "@/lib/utils";
import { ChannelDialog } from "./channel-dialog";
import { when } from "./date-range";

function StatusDot({ status, error }: { status: WebhookChannel["last_status"]; error: string | null }) {
  const label = status === "ok" ? "Last delivery succeeded" : status === "error" ? "Last delivery failed" : "Never delivered";
  return (
    <span className="inline-flex items-center gap-1.5" title={status === "error" && error ? `${label}: ${error}` : label}>
      <span
        aria-hidden="true"
        className={cn(
          "size-2 rounded-full",
          status === "ok" && "bg-signal",
          status === "error" && "bg-severity-critical",
          status === null && "bg-muted-foreground/40"
        )}
      />
      <span className="text-muted-foreground">{status === "ok" ? "ok" : status === "error" ? "error" : "none yet"}</span>
    </span>
  );
}

export function ChannelsSection({ projects }: { projects: { project_id: string; name: string }[] }) {
  const queryClient = useQueryClient();
  const channels = useQuery({ queryKey: queryKeys.admin.webhookChannels(), queryFn: listWebhookChannels });
  const events = useQuery({ queryKey: queryKeys.admin.webhookEvents(), queryFn: listWebhookEvents });

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<WebhookChannel | null>(null);
  const [deleting, setDeleting] = useState<WebhookChannel | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const nameOf = (id: string) => projects.find((p) => p.project_id === id)?.name ?? "Deleted project";

  const remove = useMutation({
    mutationFn: (id: string) => deleteWebhookChannel(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.webhookChannels() });
      toast.success("Channel deleted");
      setConfirmOpen(false);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to delete the channel"),
  });

  const test = useMutation({
    mutationFn: (c: WebhookChannel) => testWebhookChannel(c.id),
    onSuccess: (r, c) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.admin.webhookChannels() });
      if (r.ok) toast.success(`Test message delivered to ${c.name}${r.status ? ` (HTTP ${r.status})` : ""}`);
      else toast.error(`Test to ${c.name} failed${r.status ? ` (HTTP ${r.status})` : ""}: ${r.error ?? "no detail"}`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to send the test message"),
  });

  const list = channels.data ?? [];

  return (
    <div className="space-y-3">
      <SectionRule
        label="Webhook channels"
        actions={
          <Button
            size="sm"
            onClick={() => {
              setEditing(null);
              setDialogOpen(true);
            }}
          >
            <Plus /> Add channel
          </Button>
        }
      />
      <DataTableCard
        isLoading={channels.isLoading}
        isError={channels.isError}
        errorMessage="Failed to load webhook channels."
        isEmpty={list.length === 0}
        emptyState={
          <EmptyState
            title="No webhook channels"
            description="Add a channel to route failure alerts and the scheduled digest to Teams."
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 text-xs">
              <TableHead className="py-2.5">Name</TableHead>
              <TableHead className="py-2.5">Host</TableHead>
              <TableHead className="py-2.5">Enabled</TableHead>
              <TableHead className="py-2.5">Status</TableHead>
              <TableHead className="py-2.5">Last delivery</TableHead>
              <TableHead className="py-2.5">Events</TableHead>
              <TableHead className="py-2.5">Projects</TableHead>
              <TableHead className="py-2.5" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.map((c) => (
              <TableRow key={c.id} className="align-top text-xs">
                <TableCell className="font-medium text-foreground">
                  {c.name}
                  {c.include_digest && <span className="legend ml-1.5 text-muted-foreground">digest</span>}
                </TableCell>
                <TableCell className="font-mono text-muted-foreground">{c.url_host}</TableCell>
                <TableCell className={c.enabled ? "text-foreground" : "text-muted-foreground"}>
                  {c.enabled ? "Enabled" : "Disabled"}
                </TableCell>
                <TableCell>
                  <StatusDot status={c.last_status} error={c.last_error} />
                </TableCell>
                <TableCell className="whitespace-nowrap font-mono text-muted-foreground">
                  {when(c.last_delivery_at)}
                </TableCell>
                <TableCell className="font-mono tabular-nums">{c.events.length}</TableCell>
                <TableCell
                  className="max-w-48 truncate text-muted-foreground"
                  title={c.project_ids.map(nameOf).join(", ") || undefined}
                >
                  {c.project_ids.length === 0 ? "All projects" : `${c.project_ids.length} selected`}
                </TableCell>
                <TableCell>
                  <div className="flex items-center justify-end gap-1">
                    <Button
                      size="xs"
                      variant="outline"
                      disabled={test.isPending}
                      onClick={() => test.mutate(c)}
                      aria-label={`Send test to ${c.name}`}
                    >
                      <Send /> Send test
                    </Button>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Edit ${c.name}`}
                      onClick={() => {
                        setEditing(c);
                        setDialogOpen(true);
                      }}
                    >
                      <Pencil />
                    </Button>
                    <Button
                      size="icon-xs"
                      variant="ghost"
                      aria-label={`Delete ${c.name}`}
                      onClick={() => {
                        setDeleting(c);
                        setConfirmOpen(true);
                      }}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>

      <ChannelDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        channel={editing}
        events={events.data ?? []}
        projects={projects}
      />
      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={setConfirmOpen}
        title={`Delete ${deleting?.name ?? "channel"}?`}
        description="Alerts and digests will stop going to this webhook. This cannot be undone."
        confirmLabel="Delete channel"
        pendingLabel="Deleting…"
        pending={remove.isPending}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
    </div>
  );
}

"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { CopyCommand } from "@/components/common/copy-command";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, retryUnlessForbiddenOrMissing } from "@/lib/api/client";
import {
  MCP_EXPIRY_CHOICES,
  createMcpToken,
  listMcpTokens,
  mcpAddCommand,
  mcpServerOrigin,
  renameMcpToken,
  revokeMcpToken,
  type McpToken,
  type McpTokenCreated,
} from "@/lib/api/mcp-tokens";
import { queryKeys } from "@/lib/api/query-keys";
import { ConfirmDialog } from "./confirm-dialog";
import { mcpTokenStatus } from "./integration-status";
import type { IntegrationRow } from "./integrations-table";

/** Native select, deliberately: base-ui's SelectValue renders the raw value rather than the item label. */
function ExpirySelect({ id, value, onChange }: { id: string; value: number; onChange: (days: number) => void }) {
  return (
    <select
      id={id}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="h-9 rounded-md border border-input bg-background px-3 text-sm"
    >
      {MCP_EXPIRY_CHOICES.map((d) => (
        <option key={d} value={d}>
          {d} days
        </option>
      ))}
    </select>
  );
}

function RevealTokenDialog({ token, onClose }: { token: McpTokenCreated | null; onClose: () => void }) {
  return (
    <Dialog open={token !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Copy this token now</DialogTitle>
          <DialogDescription>
            You won&apos;t be able to see it again. Anyone holding it can read this portal&apos;s logs, queues and audit trail
            until it expires or is revoked.
          </DialogDescription>
        </DialogHeader>
        {token && (
          <div className="min-w-0 space-y-4">
            <div className="space-y-1.5">
              <p className="text-xs font-semibold">Token</p>
              <CopyCommand wrap>{token.raw_token}</CopyCommand>
            </div>
            <div className="space-y-1.5">
              <p className="text-xs font-semibold">Connect Claude Code</p>
              <p className="text-xs text-muted-foreground">
                Saved for your user, so it works from any folder. Run it once, then restart the editor session.
              </p>
              <CopyCommand wrap>{mcpAddCommand(mcpServerOrigin(), token.raw_token)}</CopyCommand>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button onClick={onClose}>I&apos;ve copied it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function RenameTokenDialog({ token, onClose }: { token: McpToken | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState(token?.label ?? "");

  const rename = useMutation({
    mutationFn: () => {
      if (!token) throw new Error("No token selected");
      return renameMcpToken(token.id, label.trim());
    },
    onSuccess: () => {
      toast.success("Token renamed");
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.mcpTokens() });
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to rename token"),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (label.trim()) rename.mutate();
  };

  return (
    <Dialog open={token !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Edit MCP token</DialogTitle>
            <DialogDescription>Only the label changes. The secret and its expiry stay as they are.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="mcp-rename">Label</Label>
            <Input id="mcp-rename" value={label} maxLength={80} onChange={(e) => setLabel(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={rename.isPending || !label.trim()}>
              {rename.isPending ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Reconnect for a token means a fresh secret: the old one is revoked and a new one issued under the same label. */
function ReissueTokenDialog({
  token,
  onClose,
  onIssued,
}: {
  token: McpToken | null;
  onClose: () => void;
  onIssued: (created: McpTokenCreated) => void;
}) {
  const queryClient = useQueryClient();
  const [days, setDays] = useState<number>(30);

  const reissue = useMutation({
    mutationFn: async () => {
      if (!token) throw new Error("No token selected");
      const created = await createMcpToken({ label: token.label, expires_in_days: days });
      // Issue first, revoke second: if the revoke fails the user still holds a working new token.
      let revoked = true;
      if (token.is_active) {
        try {
          await revokeMcpToken(token.id);
        } catch {
          revoked = false;
        }
      }
      return { created, revoked };
    },
    onSuccess: ({ created, revoked }) => {
      if (!revoked) toast.error("The new token works, but the old one could not be revoked. Remove it from the list.");
      void queryClient.invalidateQueries({ queryKey: queryKeys.admin.mcpTokens() });
      onClose();
      onIssued(created);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to reissue token"),
  });

  return (
    <Dialog open={token !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reconnect with a new token</DialogTitle>
          <DialogDescription>
            {token?.is_active
              ? "A new token is issued under the same label and the current one stops working immediately. Update the agent with the new command."
              : "This token has ended. A new one is issued under the same label."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="mcp-reissue-days">Expires in</Label>
          <div>
            <ExpirySelect id="mcp-reissue-days" value={days} onChange={setDays} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={reissue.isPending} onClick={() => reissue.mutate()}>
            {reissue.isPending ? "Issuing…" : "Issue new token"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The signed-in admin's MCP tokens as table rows. `enabled` must be false for non-admins: the endpoint is
 * admin-only, and a query that can only 403 just adds noise.
 */
export function useMcpTokenIntegrations(enabled: boolean) {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: queryKeys.admin.mcpTokens(),
    queryFn: listMcpTokens,
    retry: retryUnlessForbiddenOrMissing,
    enabled,
  });

  const [revealed, setRevealed] = useState<McpTokenCreated | null>(null);
  const [renaming, setRenaming] = useState<McpToken | null>(null);
  const [reissuing, setReissuing] = useState<McpToken | null>(null);
  const [removing, setRemoving] = useState<McpToken | null>(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.admin.mcpTokens() });

  const issue = useMutation({
    mutationFn: (input: { label: string; days: number }) =>
      createMcpToken({ label: input.label.trim(), expires_in_days: input.days }),
    onSuccess: (created) => {
      setRevealed(created);
      void refresh();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to issue token"),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeMcpToken(id),
    onSuccess: () => {
      toast.success("Token revoked");
      setRemoving(null);
      void refresh();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to revoke token"),
  });

  const rows: IntegrationRow[] = (list.data ?? []).map((t) => ({
    key: `mcp-${t.id}`,
    kind: "mcp_token",
    name: t.label,
    detail: `${t.prefix}…`,
    status: mcpTokenStatus(t),
    added: t.created_at,
    lastUsed: t.last_used_at,
    actions: {
      // An ended token has nothing left to edit or remove; only a replacement makes sense.
      ...(t.is_active ? { edit: () => setRenaming(t), remove: () => setRemoving(t) } : {}),
      reconnect: () => setReissuing(t),
      reconnectLabel: "Reissue",
    },
  }));

  const dialogs = (
    <>
      <RevealTokenDialog token={revealed} onClose={() => setRevealed(null)} />
      <RenameTokenDialog key={`rename-${renaming?.id ?? "none"}`} token={renaming} onClose={() => setRenaming(null)} />
      <ReissueTokenDialog
        key={`reissue-${reissuing?.id ?? "none"}`}
        token={reissuing}
        onClose={() => setReissuing(null)}
        onIssued={setRevealed}
      />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove MCP token"
        description={`${removing?.label ?? "This token"} is revoked now. Any AI agent using it loses access immediately.`}
        confirmLabel="Remove"
        pendingLabel="Removing…"
        pending={revoke.isPending}
        onConfirm={() => removing && revoke.mutate(removing.id)}
      />
    </>
  );

  return {
    rows,
    isLoading: enabled && list.isLoading,
    isError: enabled && list.isError,
    dialogs,
    issue: issue.mutate,
    isIssuing: issue.isPending,
  };
}

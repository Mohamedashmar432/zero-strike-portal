"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { CopyCommand } from "@/components/common/copy-command";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, retryUnlessForbiddenOrMissing } from "@/lib/api/client";
import {
  MCP_EXPIRY_CHOICES,
  createMcpToken,
  listMcpTokens,
  mcpAddCommand,
  mcpServerOrigin,
  revokeMcpToken,
  type McpTokenCreated,
} from "@/lib/api/mcp-tokens";
import { queryKeys } from "@/lib/api/query-keys";

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function McpAccessPage() {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState("");
  const [days, setDays] = useState<number>(30);
  const [revealed, setRevealed] = useState<McpTokenCreated | null>(null);

  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.mcpTokens(),
    queryFn: listMcpTokens,
    retry: retryUnlessForbiddenOrMissing,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: queryKeys.admin.mcpTokens() });

  const create = useMutation({
    mutationFn: () => createMcpToken({ label: label.trim(), expires_in_days: days }),
    onSuccess: (token) => {
      setRevealed(token);
      setLabel("");
      void refresh();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to issue token"),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeMcpToken(id),
    onSuccess: (_data, id) => {
      if (revealed?.id === id) setRevealed(null);
      toast.success("Token revoked");
      void refresh();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to revoke token"),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="MCP Access"
        description="Personal tokens that let an AI agent (Claude Code, Claude Desktop) read this portal's logs, queues and audit trail. Read-only; every call is audited; access ends the moment your admin role does."
      />

      {revealed && (
        <Alert className="border-severity-medium/50 bg-severity-medium/5">
          <AlertTitle>Copy this token now — you won&apos;t be able to see it again.</AlertTitle>
          <AlertDescription>
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <code className="flex-1 truncate rounded bg-muted px-2 py-1 text-xs">{revealed.raw_token}</code>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void navigator.clipboard.writeText(revealed.raw_token);
                    toast.success("Copied to clipboard");
                  }}
                >
                  Copy
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setRevealed(null)}>
                  Dismiss
                </Button>
              </div>
              <p className="text-xs text-muted-foreground">Connect Claude Code with:</p>
              <CopyCommand>{mcpAddCommand(mcpServerOrigin(), revealed.raw_token)}</CopyCommand>
            </div>
          </AlertDescription>
        </Alert>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (label.trim()) create.mutate();
        }}
        className="flex flex-wrap items-end gap-3"
      >
        <div className="space-y-2">
          <Label htmlFor="mcp-label">Label</Label>
          <Input
            id="mcp-label"
            value={label}
            maxLength={80}
            placeholder="e.g. my laptop"
            onChange={(e) => setLabel(e.target.value)}
            className="w-64"
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="mcp-expiry">Expires in</Label>
          <select
            id="mcp-expiry"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm"
          >
            {MCP_EXPIRY_CHOICES.map((d) => (
              <option key={d} value={d}>
                {d} days
              </option>
            ))}
          </select>
        </div>
        <Button type="submit" disabled={!label.trim() || create.isPending}>
          {create.isPending ? "Issuing…" : "Issue token"}
        </Button>
      </form>

      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load MCP tokens."
        isEmpty={!!data && data.length === 0}
        emptyState={<EmptyState title="No MCP tokens issued." />}
      >
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 text-xs">
              <TableHead className="py-2.5">Label</TableHead>
              <TableHead className="py-2.5">Prefix</TableHead>
              <TableHead className="py-2.5">Created</TableHead>
              <TableHead className="py-2.5">Expires</TableHead>
              <TableHead className="py-2.5">Last used</TableHead>
              <TableHead className="py-2.5">Status</TableHead>
              <TableHead className="py-2.5" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((t) => (
              <TableRow key={t.id} className="text-xs">
                <TableCell className="font-semibold text-foreground">{t.label}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{t.prefix}…</TableCell>
                <TableCell className="font-mono text-muted-foreground">{formatDate(t.created_at)}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{formatDate(t.expires_at)}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{formatDate(t.last_used_at)}</TableCell>
                <TableCell>
                  {t.revoked_at ? (
                    <Badge variant="outline">Revoked {formatDate(t.revoked_at)}</Badge>
                  ) : t.is_active ? (
                    <Badge>Active</Badge>
                  ) : (
                    <Badge variant="outline">Expired</Badge>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  {t.is_active && (
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={revoke.isPending}
                      onClick={() => revoke.mutate(t.id)}
                    >
                      Revoke
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

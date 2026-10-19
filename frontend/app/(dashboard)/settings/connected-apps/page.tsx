"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { CopyCommand } from "@/components/common/copy-command";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api/client";
import { mcpServerOrigin } from "@/lib/api/mcp-tokens";
import { listConnectedApps, revokeConnectedApp, userMcpUrl } from "@/lib/api/oauth";
import { queryKeys } from "@/lib/api/query-keys";

function formatDate(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Never";
}

export default function ConnectedAppsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.oauth.connectedApps(),
    queryFn: listConnectedApps,
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeConnectedApp(id),
    onSuccess: () => {
      toast.success("Access revoked");
      void queryClient.invalidateQueries({ queryKey: queryKeys.oauth.connectedApps() });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to revoke access"),
  });

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Connected apps</h2>
        <p className="text-sm text-muted-foreground">
          AI clients you have allowed to read your projects. They see only what you can see, read-only, and you can
          cut them off here at any time.
        </p>
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-semibold">Connect an AI client</h3>
        <p className="text-sm text-muted-foreground">
          In Claude, ChatGPT or any MCP client, add a remote connector with this URL, then sign in and approve when
          asked.
        </p>
        <CopyCommand>{userMcpUrl(mcpServerOrigin())}</CopyCommand>
      </div>

      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load connected apps."
        isEmpty={!!data && data.length === 0}
        emptyState={<EmptyState title="No connected apps." />}
      >
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 text-xs">
              <TableHead className="py-2.5">Application</TableHead>
              <TableHead className="py-2.5">Redirects to</TableHead>
              <TableHead className="py-2.5">Connected</TableHead>
              <TableHead className="py-2.5">Last used</TableHead>
              <TableHead className="py-2.5" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.map((app) => (
              <TableRow key={app.id} className="text-xs">
                <TableCell className="font-semibold text-foreground">{app.client_name}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{app.redirect_host}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{formatDate(app.created_at)}</TableCell>
                <TableCell className="font-mono text-muted-foreground">{formatDate(app.last_used_at)}</TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(app.id)}
                  >
                    Revoke
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

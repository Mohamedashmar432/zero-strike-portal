"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { listConnectedApps, revokeConnectedApp, type ConnectedApp } from "@/lib/api/oauth";
import { queryKeys } from "@/lib/api/query-keys";
import { ConfirmDialog } from "./confirm-dialog";
import type { IntegrationRow } from "./integrations-table";

/**
 * AI clients the user approved over OAuth (Claude, ChatGPT…). Re-authorizing happens in the client itself,
 * and there is nothing here to edit, so a row offers Remove only.
 */
export function useConnectedAppIntegrations() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: queryKeys.oauth.connectedApps(), queryFn: listConnectedApps });
  const [removing, setRemoving] = useState<ConnectedApp | null>(null);

  const revoke = useMutation({
    mutationFn: (id: string) => revokeConnectedApp(id),
    onSuccess: () => {
      toast.success("Access revoked");
      setRemoving(null);
      void queryClient.invalidateQueries({ queryKey: queryKeys.oauth.connectedApps() });
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to revoke access"),
  });

  const rows: IntegrationRow[] = (list.data ?? []).map((app) => ({
    key: `app-${app.id}`,
    kind: "connected_app",
    name: app.client_name,
    detail: app.redirect_host,
    status: { tone: "ok", label: "Connected" },
    added: app.created_at,
    lastUsed: app.last_used_at,
    actions: { remove: () => setRemoving(app) },
  }));

  const dialogs = (
    <ConfirmDialog
      open={removing !== null}
      onOpenChange={(open) => !open && setRemoving(null)}
      title="Remove connected app"
      description={`${removing?.client_name ?? "This app"} loses access to your projects immediately. You can connect it again from the app.`}
      confirmLabel="Remove"
      pendingLabel="Removing…"
      pending={revoke.isPending}
      onConfirm={() => removing && revoke.mutate(removing.id)}
    />
  );

  return { rows, isLoading: list.isLoading, isError: list.isError, dialogs };
}

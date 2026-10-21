"use client";

import Link from "next/link";
import { EmptyState } from "@/components/common/empty-state";
import { IntegrationsTable } from "@/components/settings/integrations/integrations-table";
import { useConnectedAppIntegrations } from "@/components/settings/integrations/use-connected-app-integrations";
import { useCredentialIntegrations } from "@/components/settings/integrations/use-credential-integrations";
import { useMcpTokenIntegrations } from "@/components/settings/integrations/use-mcp-token-integrations";
import { buttonVariants } from "@/components/ui/button";
import { useAuth } from "@/providers/auth-provider";

/** Every integration in one table, each row with the actions that make sense for what it is. */
export default function IntegrationsOverviewPage() {
  const { user } = useAuth();
  const credentials = useCredentialIntegrations();
  const tokens = useMcpTokenIntegrations(user?.role === "admin");
  const apps = useConnectedAppIntegrations();

  const rows = [...credentials.rows, ...tokens.rows, ...apps.rows];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground">
          {rows.length} integration{rows.length === 1 ? "" : "s"}
        </p>
        <div className="flex gap-2">
          <Link href="/settings/integrations/source-control" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Add source control
          </Link>
          <Link href="/settings/integrations/mcp" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Connect an AI agent
          </Link>
        </div>
      </div>
      <IntegrationsTable
        rows={rows}
        isLoading={credentials.isLoading || tokens.isLoading || apps.isLoading}
        isError={credentials.isError || tokens.isError || apps.isError}
        emptyState={
          <EmptyState
            title="No integrations yet"
            description="Add a GitHub or Azure DevOps token to connect repositories, or connect an AI agent."
          />
        }
      />
      {credentials.dialogs}
      {tokens.dialogs}
      {apps.dialogs}
    </div>
  );
}

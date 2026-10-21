"use client";

import { Bot, KeyRound } from "lucide-react";
import type { ReactNode } from "react";
import { DataTableCard } from "@/components/common/data-table-card";
import { AzureDevOpsIcon, GitHubIcon } from "@/components/repos/provider-icons";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { IntegrationStatus } from "./integration-status";
import { IntegrationStatusBadge } from "./status-badge";

export type IntegrationKind = "github" | "azure_devops" | "mcp_token" | "connected_app";

/** One line in the integrations table, whatever it is backed by. A missing action is simply not offered. */
export type IntegrationRow = {
  key: string;
  kind: IntegrationKind;
  name: string;
  /** Account, organization or token prefix: the part that tells two rows of the same kind apart. */
  detail: string;
  status: IntegrationStatus;
  added: string | null;
  lastUsed: string | null;
  actions: { edit?: () => void; reconnect?: () => void; remove?: () => void; reconnectLabel?: string };
};

const KIND: Record<IntegrationKind, { label: string; icon: ReactNode }> = {
  github: { label: "GitHub", icon: <GitHubIcon className="size-4" /> },
  azure_devops: { label: "Azure DevOps", icon: <AzureDevOpsIcon className="size-4" /> },
  mcp_token: { label: "MCP token", icon: <KeyRound className="size-4" /> },
  connected_app: { label: "AI client", icon: <Bot className="size-4" /> },
};

function formatDate(value: string | null, empty: string) {
  return value ? new Date(value).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : empty;
}

export function IntegrationsTable({
  rows,
  isLoading,
  isError,
  emptyState,
}: {
  rows: IntegrationRow[];
  isLoading: boolean;
  isError: boolean;
  emptyState: ReactNode;
}) {
  return (
    <DataTableCard
      isLoading={isLoading}
      isError={isError}
      errorMessage="Failed to load integrations."
      isEmpty={rows.length === 0}
      emptyState={emptyState}
    >
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/40 text-xs">
            <TableHead className="py-2.5">Integration</TableHead>
            <TableHead className="py-2.5">Account / detail</TableHead>
            <TableHead className="py-2.5">Status</TableHead>
            <TableHead className="py-2.5">Added</TableHead>
            <TableHead className="py-2.5">Last used</TableHead>
            <TableHead className="py-2.5 text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const kind = KIND[row.kind];
            return (
              <TableRow key={row.key} className="text-xs">
                <TableCell>
                  <div className="flex items-center gap-2.5">
                    <span className="text-muted-foreground">{kind.icon}</span>
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-foreground">{row.name}</p>
                      <p className="text-[11px] text-muted-foreground">{kind.label}</p>
                    </div>
                  </div>
                </TableCell>
                <TableCell className="max-w-56 truncate font-mono text-muted-foreground" title={row.detail}>
                  {row.detail}
                </TableCell>
                <TableCell>
                  <IntegrationStatusBadge {...row.status} />
                </TableCell>
                <TableCell className="font-mono whitespace-nowrap text-muted-foreground">
                  {formatDate(row.added, "—")}
                </TableCell>
                <TableCell className="font-mono whitespace-nowrap text-muted-foreground">
                  {formatDate(row.lastUsed, "Never")}
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1.5">
                    {row.actions.edit && (
                      <Button size="sm" variant="outline" aria-label={`Edit ${row.name}`} onClick={row.actions.edit}>
                        Edit
                      </Button>
                    )}
                    {row.actions.reconnect && (
                      <Button
                        size="sm"
                        variant="outline"
                        aria-label={`${row.actions.reconnectLabel ?? "Reconnect"} ${row.name}`}
                        onClick={row.actions.reconnect}
                      >
                        {row.actions.reconnectLabel ?? "Reconnect"}
                      </Button>
                    )}
                    {row.actions.remove && (
                      <Button
                        size="sm"
                        variant="destructive"
                        aria-label={`Remove ${row.name}`}
                        onClick={row.actions.remove}
                      >
                        Remove
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </DataTableCard>
  );
}

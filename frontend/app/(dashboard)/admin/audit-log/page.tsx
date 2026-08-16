"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listAuditLogs } from "@/lib/api/audit-logs";

export default function AdminAuditLogPage() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "audit-logs"],
    queryFn: () => listAuditLogs(),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit Log"
        description="Immutable record of security-relevant administrative actions, authentications, and policy modifications."
      />
      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load audit log."
        isEmpty={!!data && data.items.length === 0}
        emptyState={<EmptyState title="No audit events recorded yet." />}
      >
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 text-xs">
              <TableHead className="py-2.5">Timestamp</TableHead>
              <TableHead className="py-2.5">Actor Identity</TableHead>
              <TableHead className="py-2.5">Security Action</TableHead>
              <TableHead className="py-2.5">Origin IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((log) => (
              <TableRow key={log.id} className="text-xs">
                <TableCell className="font-mono text-[11px] text-muted-foreground whitespace-nowrap">
                  {new Date(log.created_at).toLocaleString()}
                </TableCell>
                <TableCell className="font-mono text-xs font-semibold text-foreground">
                  {log.actor_user_id ?? log.actor_type}
                </TableCell>
                <TableCell className="font-medium text-foreground">{log.action}</TableCell>
                <TableCell className="font-mono text-[11px] text-muted-foreground">{log.ip_address ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

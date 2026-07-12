"use client";

import { useQuery } from "@tanstack/react-query";
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
        description="A record of security-relevant actions taken across the portal."
      />
      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load audit log."
        isEmpty={!!data && data.items.length === 0}
        emptyState={<EmptyState title="No audit events yet." />}
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Action</TableHead>
              <TableHead>IP</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((log) => (
              <TableRow key={log.id}>
                <TableCell className="font-mono text-xs">
                  {new Date(log.created_at).toLocaleString()}
                </TableCell>
                <TableCell className="font-mono text-xs">{log.actor_user_id ?? log.actor_type}</TableCell>
                <TableCell>{log.action}</TableCell>
                <TableCell className="font-mono text-xs">{log.ip_address ?? "—"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>
    </div>
  );
}

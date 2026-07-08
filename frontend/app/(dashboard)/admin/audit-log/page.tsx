"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listAuditLogs } from "@/lib/api/audit-logs";

export default function AdminAuditLogPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin", "audit-logs"],
    queryFn: () => listAuditLogs(),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Audit Log</h1>
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : error ? (
            <p className="p-4 text-sm text-destructive">Failed to load audit log.</p>
          ) : data?.items.length === 0 ? (
            <p className="p-4 text-sm text-muted-foreground">No audit events yet.</p>
          ) : (
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
          )}
        </CardContent>
      </Card>
    </div>
  );
}

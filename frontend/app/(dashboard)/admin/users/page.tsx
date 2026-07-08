"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { listUsers } from "@/lib/api/users";

export default function AdminUsersPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => listUsers(),
  });

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Users</h1>
      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-8 w-full" />
              <Skeleton className="h-8 w-full" />
            </div>
          ) : error ? (
            <p className="p-4 text-sm text-destructive">Failed to load users.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Email</TableHead>
                  <TableHead>Name</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data?.items.map((u) => (
                  <TableRow key={u.id}>
                    <TableCell className="font-mono text-xs">{u.email}</TableCell>
                    <TableCell>{u.name}</TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="font-mono uppercase">
                        {u.role}
                      </Badge>
                    </TableCell>
                    <TableCell>{u.is_active ? "Active" : "Disabled"}</TableCell>
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

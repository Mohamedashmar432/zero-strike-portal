"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError } from "@/lib/api/client";
import { listUsers, updateUserRole } from "@/lib/api/users";
import { useAuth } from "@/providers/auth-provider";

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const { data, isLoading, error } = useQuery({
    queryKey: ["admin", "users"],
    queryFn: () => listUsers(),
  });

  const setRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: "admin" | "user" }) => updateUserRole(userId, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("Role updated");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update role"),
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
                  <TableHead />
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
                    <TableCell>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={u.id === currentUser?.id || setRole.isPending}
                        title={u.id === currentUser?.id ? "You can't change your own role" : undefined}
                        onClick={() =>
                          setRole.mutate({ userId: u.id, role: u.role === "admin" ? "user" : "admin" })
                        }
                      >
                        {u.role === "admin" ? "Revert to user" : "Make admin"}
                      </Button>
                    </TableCell>
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

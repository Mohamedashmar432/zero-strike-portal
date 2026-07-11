"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { User } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { deleteUser, listUsers, updateUser } from "@/lib/api/users";
import { useAuth } from "@/providers/auth-provider";

const PAGE_SIZE = 20;

function UserRowActions({
  targetUser,
  isSelf,
  onRequestDelete,
}: {
  targetUser: User;
  isSelf: boolean;
  onRequestDelete: (user: User) => void;
}) {
  const queryClient = useQueryClient();

  const toggleRole = useMutation({
    mutationFn: () => updateUser(targetUser.id, { role: targetUser.role === "admin" ? "user" : "admin" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(targetUser.role === "admin" ? "User demoted to user" : "User promoted to admin");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update role"),
  });

  const toggleActive = useMutation({
    mutationFn: () => updateUser(targetUser.id, { is_active: !targetUser.is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(targetUser.is_active ? "User disabled" : "User enabled");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update user"),
  });

  return (
    <div className="flex flex-wrap gap-2">
      <Button
        variant="outline"
        size="sm"
        disabled={isSelf || toggleRole.isPending}
        onClick={() => toggleRole.mutate()}
      >
        {targetUser.role === "admin" ? "Demote to user" : "Promote to admin"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={isSelf || toggleActive.isPending}
        onClick={() => toggleActive.mutate()}
      >
        {targetUser.is_active ? "Disable" : "Enable"}
      </Button>
      <Button variant="destructive" size="sm" disabled={isSelf} onClick={() => onRequestDelete(targetUser)}>
        Delete
      </Button>
    </div>
  );
}

export default function AdminUsersPage() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [deleteTarget, setDeleteTarget] = useState<User | null>(null);

  const { data, isLoading, error } = useQuery({
    queryKey: ["admin", "users", page],
    queryFn: () => listUsers(page, PAGE_SIZE),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("User deleted");
      setDeleteTarget(null);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to delete user"),
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

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
                {data?.items.map((u) => {
                  const isSelf = u.id === currentUser?.id;
                  return (
                    <TableRow key={u.id}>
                      <TableCell className="font-mono text-xs">{u.email}</TableCell>
                      <TableCell>
                        {u.name}
                        {isSelf && <span className="ml-1 text-xs text-muted-foreground">(you)</span>}
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary" className="font-mono uppercase">
                          {u.role}
                        </Badge>
                      </TableCell>
                      <TableCell>{u.is_active ? "Active" : "Disabled"}</TableCell>
                      <TableCell>
                        <UserRowActions targetUser={u} isSelf={isSelf} onRequestDelete={setDeleteTarget} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      {data && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-muted-foreground">
            Page {data.page} of {totalPages}
          </p>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete user</DialogTitle>
            <DialogDescription>
              This will permanently delete {deleteTarget?.email}. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
            >
              {deleteMutation.isPending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

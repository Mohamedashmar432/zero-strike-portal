"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { RowActionsMenu } from "@/components/common/row-actions";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { PageHeader } from "@/components/layout/page-header";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Textarea } from "@/components/ui/textarea";
import { ShieldCheck, Trash2, UserCheck, UserX } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { User } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/client";
import { approveUser, deleteUser, listUsers, rejectUser, updateUser } from "@/lib/api/users";
import { roleLabel } from "@/lib/role-labels";
import { getInitials } from "@/lib/utils";
import { useAuth } from "@/providers/auth-provider";

const PAGE_SIZE = 20;

function UserRowActions({
  targetUser,
  isSelf,
  onRequestDelete,
  onRequestDecline,
  onRequestRoleChange,
}: {
  targetUser: User;
  isSelf: boolean;
  onRequestDelete: (user: User) => void;
  onRequestDecline: (user: User) => void;
  onRequestRoleChange: (user: User) => void;
}) {
  const queryClient = useQueryClient();

  const approve = useMutation({
    mutationFn: () => approveUser(targetUser.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(`Approved ${targetUser.email}. They have been emailed.`);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to approve"),
  });

  const toggleActive = useMutation({
    mutationFn: () => updateUser(targetUser.id, { is_active: !targetUser.is_active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(targetUser.is_active ? "User disabled" : "User enabled");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update user"),
  });

  if (targetUser.approval_status !== "approved") {
    return (
      <div className="flex items-center gap-1">
        <Button size="sm" disabled={approve.isPending} onClick={() => approve.mutate()}>
          {approve.isPending ? "Approving…" : "Approve"}
        </Button>
        <RowActionsMenu label={`Actions for ${targetUser.email}`}>
          {targetUser.approval_status === "pending" && (
            <DropdownMenuItem onClick={() => onRequestDecline(targetUser)}>
              <UserX /> Decline
            </DropdownMenuItem>
          )}
          <DropdownMenuItem variant="destructive" onClick={() => onRequestDelete(targetUser)}>
            <Trash2 /> Delete
          </DropdownMenuItem>
        </RowActionsMenu>
      </div>
    );
  }
  return (
    <RowActionsMenu label={`Actions for ${targetUser.email}`}>
      <DropdownMenuItem disabled={isSelf} onClick={() => onRequestRoleChange(targetUser)}>
        <ShieldCheck />
        {targetUser.role === "admin" ? `Demote to ${roleLabel("user")}` : `Promote to ${roleLabel("admin")}`}
      </DropdownMenuItem>
      <DropdownMenuItem disabled={isSelf || toggleActive.isPending} onClick={() => toggleActive.mutate()}>
        {targetUser.is_active ? <UserX /> : <UserCheck />}
        {targetUser.is_active ? "Disable" : "Enable"}
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem variant="destructive" disabled={isSelf} onClick={() => onRequestDelete(targetUser)}>
        <Trash2 /> Delete
      </DropdownMenuItem>
    </RowActionsMenu>
  );
}

function statusLabel(u: User) {
  if (u.approval_status === "pending") return "Awaiting approval";
  if (u.approval_status === "rejected") return "Declined";
  return u.is_active ? "Active" : "Disabled";
}

export default function AdminUsersPage() {
  // useSearchParams needs a Suspense boundary or the route cannot be prerendered.
  return (
    <Suspense fallback={null}>
      <AdminUsers />
    </Suspense>
  );
}

function AdminUsers() {
  const { user: currentUser } = useAuth();
  const queryClient = useQueryClient();
  const router = useRouter();
  // ?status=pending is where the "new signup request" email and notification link to.
  const pendingOnly = useSearchParams().get("status") === "pending";
  const [page, setPage] = useState(1);
  const [declineTarget, setDeclineTarget] = useState<User | null>(null);
  const [declineReason, setDeclineReason] = useState("");
  // Two separate pieces of state rather than one `deleteTarget: User | null`:
  // deleteTargetId controls the dialog's open state and is nulled on success/cancel,
  // but deleteTargetEmail is intentionally left stale so the ~100ms dialog exit
  // animation doesn't render "undefined" while the content is still mounted.
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);
  const [deleteTargetEmail, setDeleteTargetEmail] = useState<string | null>(null);
  // roleTarget keeps the dialog text through the exit animation; roleOpen drives visibility.
  const [roleTarget, setRoleTarget] = useState<User | null>(null);
  const [roleOpen, setRoleOpen] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ["admin", "users", page, pendingOnly],
    queryFn: () => listUsers(page, PAGE_SIZE, pendingOnly ? "pending" : undefined),
  });

  // Always fetched, so the tab shows a live count even while looking at All users.
  const pendingCount = useQuery({
    queryKey: ["admin", "users", "pending-count"],
    queryFn: () => listUsers(1, 1, "pending"),
  }).data?.total;

  const declineMutation = useMutation({
    mutationFn: () => rejectUser(declineTarget!.id, declineReason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("Request declined. The applicant has been emailed.");
      setDeclineTarget(null);
      setDeclineReason("");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to decline"),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteUser(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success("User deleted");
      setDeleteTargetId(null);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to delete user"),
  });

  const roleMutation = useMutation({
    mutationFn: (u: User) => updateUser(u.id, { role: u.role === "admin" ? "user" : "admin" }),
    onSuccess: (_, u) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast.success(
        u.role === "admin" ? `User demoted to ${roleLabel("user")}` : `User promoted to ${roleLabel("admin")}`
      );
      setRoleOpen(false);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update role"),
  });

  const promoting = roleTarget?.role !== "admin";

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  // Deleting the last user on the last page (or the page shrinking otherwise)
  // can leave `page` past the new `totalPages` — snap back so the table isn't
  // left showing an empty "Page N of M" with only Prev enabled. Adjusted here
  // during render (React's "adjusting state when a prop changes" pattern)
  // rather than in a useEffect, which would cause an extra render pass.
  const [prevTotalPages, setPrevTotalPages] = useState(totalPages);
  if (totalPages !== prevTotalPages) {
    setPrevTotalPages(totalPages);
    if (page > totalPages) {
      setPage(totalPages);
    }
  }

  function requestDelete(u: User) {
    setDeleteTargetId(u.id);
    setDeleteTargetEmail(u.email);
  }

  return (
    <div className="space-y-6">
      <PageHeader title="Users" description="Manage portal accounts, roles, and access." />
      <div className="flex gap-2">
        <Button
          variant={pendingOnly ? "outline" : "default"}
          size="sm"
          onClick={() => {
            setPage(1);
            router.push("/admin/users");
          }}
        >
          All users
        </Button>
        <Button
          variant={pendingOnly ? "default" : "outline"}
          size="sm"
          onClick={() => {
            setPage(1);
            router.push("/admin/users?status=pending");
          }}
        >
          Pending approval{pendingCount ? ` (${pendingCount})` : ""}
        </Button>
      </div>
      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load users."
        isEmpty={!!data && data.items.length === 0}
        emptyState={<EmptyState title={pendingOnly ? "No requests are waiting" : "No users found"} />}
      >
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
                    <div className="flex items-center gap-2">
                      <Avatar size="sm">
                        <AvatarFallback>{getInitials(u.name)}</AvatarFallback>
                      </Avatar>
                      <span>
                        {u.name}
                        {isSelf && <span className="ml-1 text-xs text-muted-foreground">(you)</span>}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{roleLabel(u.role)}</Badge>
                  </TableCell>
                  <TableCell>{statusLabel(u)}</TableCell>
                  <TableCell>
                    <UserRowActions
                      targetUser={u}
                      isSelf={isSelf}
                      onRequestDelete={requestDelete}
                      onRequestDecline={setDeclineTarget}
                      onRequestRoleChange={(user) => {
                        setRoleTarget(user);
                        setRoleOpen(true);
                      }}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </DataTableCard>
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
      <Dialog open={declineTarget !== null} onOpenChange={(open) => !open && setDeclineTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Decline access request</DialogTitle>
            <DialogDescription>
              {declineTarget?.email} will be emailed and will not be able to sign in. The reason is
              optional and is included in that email.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            aria-label="Reason (optional)"
            placeholder="Reason (optional)"
            maxLength={500}
            value={declineReason}
            onChange={(e) => setDeclineReason(e.target.value)}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeclineTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={declineMutation.isPending}
              onClick={() => declineMutation.mutate()}
            >
              {declineMutation.isPending ? "Declining…" : "Decline request"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ConfirmDialog
        open={roleOpen}
        onOpenChange={setRoleOpen}
        title={
          promoting
            ? `Make ${roleTarget?.email ?? ""} an administrator?`
            : `Remove administrator access from ${roleTarget?.email ?? ""}?`
        }
        description={
          promoting
            ? "Administrators can manage every user, AI provider and workspace setting."
            : "They lose access to the admin pages and workspace settings."
        }
        confirmLabel={promoting ? `Promote to ${roleLabel("admin")}` : `Demote to ${roleLabel("user")}`}
        pendingLabel="Saving…"
        pending={roleMutation.isPending}
        destructive={!promoting}
        onConfirm={() => roleTarget && roleMutation.mutate(roleTarget)}
      />
      <Dialog open={deleteTargetId !== null} onOpenChange={(open) => !open && setDeleteTargetId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete user</DialogTitle>
            <DialogDescription>
              This will permanently delete {deleteTargetEmail}. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTargetId(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={deleteMutation.isPending}
              onClick={() => deleteTargetId && deleteMutation.mutate(deleteTargetId)}
            >
              {deleteMutation.isPending ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

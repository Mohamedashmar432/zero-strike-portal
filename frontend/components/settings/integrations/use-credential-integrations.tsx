"use client";

import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api/client";
import {
  deleteRepoCredential,
  getCredentialStatus,
  listRepoCredentials,
  reconnectRepoCredential,
  updateRepoCredential,
  type RepoCredential,
} from "@/lib/api/repo-credentials";
import { normalizeAdoOrganization } from "@/lib/validation/repo-credential.schema";
import { ConfirmDialog } from "./confirm-dialog";
import { credentialStatus } from "./integration-status";
import type { IntegrationRow } from "./integrations-table";

const KEY = ["repo-credentials"] as const;
const providerName = (c: RepoCredential) => (c.provider === "azure_devops" ? "Azure DevOps" : "GitHub");
const displayName = (c: RepoCredential) => c.label || providerName(c);

function EditCredentialDialog({ credential, onClose }: { credential: RepoCredential | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  // Keyed by id below, so the form state is fresh for every credential instead of syncing it in an effect.
  const [label, setLabel] = useState(credential?.label ?? "");
  const [organization, setOrganization] = useState(credential?.organization ?? "");
  const [project, setProject] = useState(credential?.ado_project ?? "");
  const isAdo = credential?.provider === "azure_devops";

  const save = useMutation({
    mutationFn: () => {
      if (!credential) throw new Error("No credential selected");
      const org = isAdo ? normalizeAdoOrganization(organization) : organization.trim();
      const changes: Parameters<typeof updateRepoCredential>[1] = {};
      if (label.trim() !== (credential.label ?? "")) changes.label = label.trim() || null;
      if (org !== credential.organization) changes.organization = org;
      if (isAdo && (project.trim() || null) !== credential.ado_project) changes.ado_project = project.trim() || null;
      return Object.keys(changes).length ? updateRepoCredential(credential.id, changes) : Promise.resolve(null);
    },
    onSuccess: (updated) => {
      if (updated) {
        toast.success("Integration updated");
        void queryClient.invalidateQueries({ queryKey: KEY });
      }
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update integration"),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (organization.trim()) save.mutate();
  };

  return (
    <Dialog open={credential !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Edit {credential ? providerName(credential) : "integration"}</DialogTitle>
            <DialogDescription>
              Changing the {isAdo ? "organization or project" : "account"} checks the saved token against it first.
              To use a different token, choose Reconnect.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="cred-label">Label</Label>
            <Input id="cred-label" value={label} maxLength={80} placeholder="e.g. Work account" onChange={(e) => setLabel(e.target.value)} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="cred-org">{isAdo ? "Organization" : "GitHub user or organization"}</Label>
            <Input id="cred-org" value={organization} onChange={(e) => setOrganization(e.target.value)} />
          </div>
          {isAdo && (
            <div className="space-y-2">
              <Label htmlFor="cred-project">Default project (optional)</Label>
              <Input id="cred-project" value={project} placeholder="Chosen per repository when empty" onChange={(e) => setProject(e.target.value)} />
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={save.isPending || !organization.trim()}>
              {save.isPending ? "Saving…" : "Save changes"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReconnectCredentialDialog({ credential, onClose }: { credential: RepoCredential | null; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [pat, setPat] = useState("");

  const reconnect = useMutation({
    mutationFn: () => {
      if (!credential) throw new Error("No credential selected");
      return reconnectRepoCredential(credential.id, pat.trim());
    },
    onSuccess: () => {
      toast.success("Token replaced and verified");
      void queryClient.invalidateQueries({ queryKey: KEY });
      onClose();
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to reconnect"),
  });

  return (
    <Dialog open={credential !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (pat.trim()) reconnect.mutate();
          }}
          className="grid gap-4"
        >
          <DialogHeader>
            <DialogTitle>Reconnect {credential ? displayName(credential) : ""}</DialogTitle>
            <DialogDescription>
              Paste a new Personal Access Token for {credential?.organization}. It is verified with{" "}
              {credential ? providerName(credential) : "the provider"} before it replaces the old one. Repositories
              already connected to a project keep using the token they were connected with.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="cred-pat">Personal Access Token</Label>
            <Input id="cred-pat" type="password" autoComplete="off" value={pat} onChange={(e) => setPat(e.target.value)} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={reconnect.isPending || !pat.trim()}>
              {reconnect.isPending ? "Verifying…" : "Reconnect"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Saved GitHub / Azure DevOps credentials as table rows, with a live status per row and the dialogs behind Edit, Reconnect and Remove. */
export function useCredentialIntegrations() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: KEY, queryFn: listRepoCredentials });
  const credentials = list.data ?? [];
  // One provider call per credential; cached so revisiting the page doesn't re-hit GitHub / Azure DevOps.
  const statuses = useQueries({
    queries: credentials.map((c) => ({
      queryKey: [...KEY, c.id, "status"] as const,
      queryFn: () => getCredentialStatus(c.id),
      staleTime: 5 * 60_000,
      retry: false,
      refetchOnWindowFocus: false,
    })),
  });

  const [editing, setEditing] = useState<RepoCredential | null>(null);
  const [reconnecting, setReconnecting] = useState<RepoCredential | null>(null);
  const [removing, setRemoving] = useState<RepoCredential | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => deleteRepoCredential(id),
    onSuccess: () => {
      toast.success("Integration removed");
      void queryClient.invalidateQueries({ queryKey: KEY });
      setRemoving(null);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to remove integration"),
  });

  const rows: IntegrationRow[] = credentials.map((c, i) => ({
    key: `credential-${c.id}`,
    kind: c.provider,
    name: displayName(c),
    detail: c.ado_project ? `${c.organization} / ${c.ado_project}` : c.organization,
    status: credentialStatus(statuses[i] ?? { isLoading: true, isError: false }),
    added: c.created_at,
    lastUsed: null,
    actions: { edit: () => setEditing(c), reconnect: () => setReconnecting(c), remove: () => setRemoving(c) },
  }));

  const dialogs = (
    <>
      <EditCredentialDialog key={`edit-${editing?.id ?? "none"}`} credential={editing} onClose={() => setEditing(null)} />
      <ReconnectCredentialDialog
        key={`reconnect-${reconnecting?.id ?? "none"}`}
        credential={reconnecting}
        onClose={() => setReconnecting(null)}
      />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title="Remove integration"
        description={`${removing ? displayName(removing) : "This credential"} will be deleted from your saved credentials. Repositories already connected to a project keep working with the token they were connected with.`}
        confirmLabel="Remove"
        pendingLabel="Removing…"
        pending={remove.isPending}
        onConfirm={() => removing && remove.mutate(removing.id)}
      />
    </>
  );

  return { rows, isLoading: list.isLoading, isError: list.isError, dialogs };
}

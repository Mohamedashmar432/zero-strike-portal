"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { CredentialForm } from "@/components/repos/credential-form";
import { ProviderPicker } from "@/components/repos/provider-picker";
import { RepoPickerList } from "@/components/repos/repo-picker-list";
import { SelectedRepoSummary } from "@/components/repos/selected-repo-summary";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ApiError } from "@/lib/api/client";
import { addProjectRepo, type ProjectRepo } from "@/lib/api/project-repos";
import {
  listCredentialBranches,
  listCredentialRepos,
  listRepoCredentials,
  type Provider,
  type Repo,
} from "@/lib/api/repo-credentials";

const PROVIDER_LABEL: Record<Provider, string> = { github: "GitHub", azure_devops: "Azure DevOps" };

// Shared by /projects/[projectId]/repos/new (standalone) and /projects/new (embedded
// right after project creation) — same credential -> repo -> branch -> label flow either way.
export function RepoConnectWizard({
  projectId,
  onConnected,
  cancelHref,
  cancelLabel = "Cancel",
  onCancel,
}: {
  projectId: string;
  onConnected: (repo: ProjectRepo) => void;
  // Exactly one of cancelHref (navigates away, standalone-page usage) or onCancel
  // (pops back to a caller-managed step, inline-embedded usage) should be given.
  cancelHref?: string;
  cancelLabel?: string;
  onCancel?: () => void;
}) {
  const queryClient = useQueryClient();

  const [provider, setProvider] = useState<Provider | null>(null);
  const [addingCredential, setAddingCredential] = useState(false);
  const [credentialId, setCredentialId] = useState<string | null>(null);
  const [repoQuery, setRepoQuery] = useState("");
  const [selectedRepo, setSelectedRepo] = useState<Repo | null>(null);
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null);
  const [label, setLabel] = useState("");

  const { data: credentials } = useQuery({
    queryKey: ["repo-credentials"],
    queryFn: listRepoCredentials,
  });
  const providerCredentials = credentials?.filter((c) => c.provider === provider);

  const {
    data: repos,
    isLoading: reposLoading,
    isError: reposError,
  } = useQuery({
    queryKey: ["repo-credentials", credentialId, "repos", repoQuery],
    queryFn: () => listCredentialRepos(credentialId!, repoQuery),
    enabled: !!credentialId,
  });

  const repoIdForBranches = selectedRepo ? (provider === "github" ? selectedRepo.full_name : selectedRepo.id) : null;

  const { data: branches, isLoading: branchesLoading } = useQuery({
    queryKey: ["repo-credentials", credentialId, "branches", repoIdForBranches],
    queryFn: () => listCredentialBranches(credentialId!, repoIdForBranches!),
    enabled: !!credentialId && !!repoIdForBranches,
  });

  const add = useMutation({
    mutationFn: () =>
      addProjectRepo(projectId, {
        credential_id: credentialId!,
        repo_full_name: selectedRepo!.full_name,
        clone_url: selectedRepo!.clone_url,
        selected_branch: selectedBranch!,
        label: label || undefined,
      }),
    onSuccess: (repo) => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId, "repos"] });
      toast.success("Repository connected");
      onConnected(repo);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to connect repository"),
  });

  const step = !provider ? 1 : !credentialId ? 2 : !selectedRepo ? 3 : !selectedBranch ? 4 : 5;

  return (
    <Card className="mx-auto max-w-xl">
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">Step {step} of 5</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!provider ? (
          <ProviderPicker onSelect={setProvider} />
        ) : !credentialId ? (
          addingCredential ? (
            <CredentialForm
              provider={provider}
              onCreated={(created) => {
                setAddingCredential(false);
                setCredentialId(created.id);
              }}
            />
          ) : (
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => {
                  setProvider(null);
                  setAddingCredential(false);
                }}
                className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="size-3.5" />
                Change provider
              </button>
              <Label>{PROVIDER_LABEL[provider]} credential</Label>
              {providerCredentials?.length ? (
                <Select value={credentialId ?? undefined} onValueChange={(value) => setCredentialId(value ?? null)}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder={`Choose a saved ${PROVIDER_LABEL[provider]} credential…`} />
                  </SelectTrigger>
                  <SelectContent>
                    {providerCredentials.map((c) => (
                      <SelectItem key={c.id} value={c.id}>
                        {c.label || c.organization}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="text-sm text-muted-foreground">No saved {PROVIDER_LABEL[provider]} credentials yet.</p>
              )}
              <Button type="button" variant="outline" size="sm" onClick={() => setAddingCredential(true)}>
                + Add new credential
              </Button>
            </div>
          )
        ) : !selectedRepo ? (
          <div className="space-y-2">
            <Input
              placeholder="Search repos…"
              autoComplete="off"
              value={repoQuery}
              onChange={(e) => setRepoQuery(e.target.value)}
            />
            <RepoPickerList repos={repos} isLoading={reposLoading} isError={reposError} onSelect={setSelectedRepo} />
          </div>
        ) : !selectedBranch ? (
          <div className="space-y-2">
            <SelectedRepoSummary repo={selectedRepo} onChange={() => setSelectedRepo(null)} />
            <Label>Branch</Label>
            <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-1">
              {branchesLoading ? (
                <p className="p-2 text-sm text-muted-foreground">Loading…</p>
              ) : branches?.length ? (
                branches.map((b) => (
                  <button
                    key={b.name}
                    type="button"
                    className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                    onClick={() => setSelectedBranch(b.name)}
                  >
                    {b.name}
                  </button>
                ))
              ) : (
                <p className="p-2 text-sm text-muted-foreground">No branches found.</p>
              )}
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
              <span className="truncate font-mono">
                {selectedRepo.full_name} @ {selectedBranch}
              </span>
              <Button type="button" size="sm" variant="ghost" onClick={() => setSelectedBranch(null)}>
                Change
              </Button>
            </div>
            <div className="space-y-2">
              <Label htmlFor="repo-label">Label (optional)</Label>
              <Input id="repo-label" value={label} onChange={(e) => setLabel(e.target.value)} autoComplete="off" />
            </div>
          </div>
        )}
        <div className="flex items-center justify-between border-t border-border pt-4">
          {onCancel ? (
            <Button variant="ghost" type="button" onClick={onCancel}>
              {cancelLabel}
            </Button>
          ) : (
            <Button variant="ghost" nativeButton={false} render={<Link href={cancelHref!} />}>
              {cancelLabel}
            </Button>
          )}
          {selectedBranch && (
            <Button onClick={() => add.mutate()} disabled={add.isPending}>
              {add.isPending ? "Connecting…" : "Connect repository"}
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

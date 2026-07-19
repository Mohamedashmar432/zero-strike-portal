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
import { getPublicGithubRepo, listPublicGithubBranches, parseGithubOwnerRepo } from "@/lib/api/public-repos";
import { queryKeys } from "@/lib/api/query-keys";
import {
  listCredentialBranches,
  listCredentialRepos,
  listRepoCredentials,
  type Provider,
  type Repo,
} from "@/lib/api/repo-credentials";

const PROVIDER_LABEL: Record<Provider, string> = { github: "GitHub", azure_devops: "Azure DevOps" };

type AccessMode = "credential" | "public";

// Shared by /projects/[projectId]/repos/new (standalone) and /projects/new (embedded
// right after project creation) — same provider -> repo -> branch -> label flow either way.
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
  // Only GitHub offers a choice — Azure DevOps always goes through a credential.
  const [mode, setMode] = useState<AccessMode | null>(null);
  const effectiveMode: AccessMode | null = provider === "azure_devops" ? "credential" : mode;
  const [addingCredential, setAddingCredential] = useState(false);
  const [credentialId, setCredentialId] = useState<string | null>(null);
  const [repoQuery, setRepoQuery] = useState("");
  const [publicRepoInput, setPublicRepoInput] = useState("");
  const [selectedRepo, setSelectedRepo] = useState<Repo | null>(null);
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null);
  const [label, setLabel] = useState("");

  const { data: credentials } = useQuery({
    queryKey: queryKeys.repoCredentials.all(),
    queryFn: listRepoCredentials,
  });
  const providerCredentials = credentials?.filter((c) => c.provider === provider);

  const {
    data: credentialRepos,
    isLoading: credentialReposLoading,
    isError: credentialReposError,
  } = useQuery({
    queryKey: queryKeys.repoCredentials.repos(credentialId ?? "", repoQuery),
    queryFn: () => listCredentialRepos(credentialId!, repoQuery),
    enabled: effectiveMode === "credential" && !!credentialId,
  });

  const repoIdForBranches = selectedRepo ? (provider === "github" ? selectedRepo.full_name : selectedRepo.id) : null;

  const { data: credentialBranches, isLoading: credentialBranchesLoading } = useQuery({
    queryKey: queryKeys.repoCredentials.branches(credentialId ?? "", repoIdForBranches ?? ""),
    queryFn: () => listCredentialBranches(credentialId!, repoIdForBranches!),
    enabled: effectiveMode === "credential" && !!credentialId && !!repoIdForBranches,
  });

  const { data: publicBranches, isLoading: publicBranchesLoading } = useQuery({
    queryKey: queryKeys.repoCredentials.branches("public", selectedRepo?.full_name ?? ""),
    queryFn: () => {
      const parsed = parseGithubOwnerRepo(selectedRepo!.full_name);
      return listPublicGithubBranches(parsed!.owner, parsed!.repo);
    },
    enabled: effectiveMode === "public" && !!selectedRepo,
  });

  const branches = effectiveMode === "public" ? publicBranches : credentialBranches;
  const branchesLoading = effectiveMode === "public" ? publicBranchesLoading : credentialBranchesLoading;

  const publicLookup = useMutation({
    mutationFn: () => {
      const parsed = parseGithubOwnerRepo(publicRepoInput);
      if (!parsed) {
        throw new Error('Enter as "owner/repo" or a full GitHub URL');
      }
      return getPublicGithubRepo(parsed.owner, parsed.repo);
    },
    onSuccess: (repo) => setSelectedRepo(repo),
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Repo lookup failed"),
  });

  const add = useMutation({
    mutationFn: () =>
      addProjectRepo(
        projectId,
        effectiveMode === "public"
          ? {
              public: true,
              provider: "github",
              repo_full_name: selectedRepo!.full_name,
              clone_url: selectedRepo!.clone_url,
              selected_branch: selectedBranch!,
              label: label || undefined,
            }
          : {
              credential_id: credentialId!,
              repo_full_name: selectedRepo!.full_name,
              clone_url: selectedRepo!.clone_url,
              selected_branch: selectedBranch!,
              label: label || undefined,
            }
      ),
    onSuccess: (repo) => {
      queryClient.invalidateQueries({ queryKey: queryKeys.projects.repos(projectId) });
      toast.success("Repository connected");
      onConnected(repo);
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to connect repository"),
  });

  const stages =
    provider === "azure_devops"
      ? ["provider", "credential", "repo", "branch", "label"]
      : effectiveMode === "public"
        ? ["provider", "mode", "lookup", "branch", "label"]
        : ["provider", "mode", "credential", "repo", "branch", "label"];
  const currentStage = !provider
    ? "provider"
    : provider === "github" && !mode
      ? "mode"
      : effectiveMode === "credential" && !credentialId
        ? "credential"
        : !selectedRepo
          ? effectiveMode === "public"
            ? "lookup"
            : "repo"
          : !selectedBranch
            ? "branch"
            : "label";
  const step = stages.indexOf(currentStage) + 1;

  function backToProvider() {
    setProvider(null);
    setMode(null);
    setAddingCredential(false);
  }

  function backToMode() {
    setMode(null);
    setSelectedRepo(null);
    setSelectedBranch(null);
  }

  return (
    <Card className="mx-auto max-w-xl">
      <CardHeader>
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Step {step} of {stages.length}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!provider ? (
          <ProviderPicker onSelect={setProvider} />
        ) : provider === "github" && !mode ? (
          <div className="space-y-2">
            <button
              type="button"
              onClick={backToProvider}
              className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
            >
              <ArrowLeft className="size-3.5" />
              Change provider
            </button>
            <Label>How should this repo be accessed?</Label>
            <button
              type="button"
              onClick={() => setMode("public")}
              className="w-full rounded-md border border-border p-3 text-left transition-colors hover:border-primary/50 hover:bg-accent"
            >
              <p className="text-sm font-medium text-foreground">Public repo — no credential needed</p>
              <p className="text-xs text-muted-foreground">For open-source repos anyone can clone.</p>
            </button>
            <button
              type="button"
              onClick={() => setMode("credential")}
              className="w-full rounded-md border border-border p-3 text-left transition-colors hover:border-primary/50 hover:bg-accent"
            >
              <p className="text-sm font-medium text-foreground">Private repo — use a credential</p>
              <p className="text-xs text-muted-foreground">
                Requires a saved or one-off Personal Access Token.
              </p>
            </button>
          </div>
        ) : effectiveMode === "credential" && !credentialId ? (
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
                onClick={provider === "github" ? backToMode : backToProvider}
                className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="size-3.5" />
                {provider === "github" ? "Back" : "Change provider"}
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
          effectiveMode === "public" ? (
            <div className="space-y-2">
              <button
                type="button"
                onClick={backToMode}
                className="mb-1 flex items-center gap-1 text-xs font-medium text-muted-foreground hover:text-foreground"
              >
                <ArrowLeft className="size-3.5" />
                Back
              </button>
              <Label htmlFor="public-repo">Repository</Label>
              <Input
                id="public-repo"
                placeholder="owner/repo or https://github.com/owner/repo"
                autoComplete="off"
                value={publicRepoInput}
                onChange={(e) => setPublicRepoInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    publicLookup.mutate();
                  }
                }}
              />
              <Button
                type="button"
                size="sm"
                onClick={() => publicLookup.mutate()}
                disabled={!publicRepoInput.trim() || publicLookup.isPending}
              >
                {publicLookup.isPending ? "Looking up…" : "Look up repo"}
              </Button>
            </div>
          ) : (
            <div className="space-y-2">
              <Input
                placeholder="Search repos…"
                autoComplete="off"
                value={repoQuery}
                onChange={(e) => setRepoQuery(e.target.value)}
              />
              <RepoPickerList
                repos={credentialRepos}
                isLoading={credentialReposLoading}
                isError={credentialReposError}
                onSelect={setSelectedRepo}
              />
            </div>
          )
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

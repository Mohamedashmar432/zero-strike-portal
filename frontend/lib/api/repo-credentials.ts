import { apiFetch } from "./client";

export type Provider = "github" | "azure_devops";

export type RepoCredential = {
  id: string;
  provider: Provider;
  organization: string;
  ado_project: string | null;
  label: string | null;
  created_at: string;
};

export type Repo = {
  id: string;
  name: string;
  full_name: string;
  clone_url: string;
  private: boolean;
  default_branch: string | null;
};

export type Branch = { name: string };

export function listRepoCredentials() {
  return apiFetch<RepoCredential[]>("/repo-credentials");
}

export function createRepoCredential(input: {
  provider: Provider;
  pat: string;
  organization: string;
  ado_project?: string;
  label?: string;
}) {
  return apiFetch<RepoCredential>("/repo-credentials", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function deleteRepoCredential(id: string) {
  return apiFetch<void>(`/repo-credentials/${id}`, { method: "DELETE" });
}

export function listCredentialRepos(credentialId: string, query = "", page = 1) {
  const params = new URLSearchParams({ page: String(page), ...(query ? { query } : {}) });
  return apiFetch<Repo[]>(`/repo-credentials/${credentialId}/repos?${params}`);
}

// repoId is "owner/repo" for GitHub or a repo GUID for Azure DevOps — never URI-encoded, the
// backend's route matches the raw path (including GitHub's literal "/").
export function listCredentialBranches(credentialId: string, repoId: string) {
  return apiFetch<Branch[]>(`/repo-credentials/${credentialId}/repos/${repoId}/branches`);
}

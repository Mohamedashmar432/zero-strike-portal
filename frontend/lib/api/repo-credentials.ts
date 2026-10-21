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

export type CredentialStatus = {
  status: "connected" | "invalid";
  detail: string | null;
  checked_at: string;
};

// A live provider call (there is no token-introspection endpoint), so cache it rather than refetch on focus.
export function getCredentialStatus(id: string) {
  return apiFetch<CredentialStatus>(`/repo-credentials/${id}/status`);
}

// Only the keys present are changed; `ado_project: null` clears the default project.
export function updateRepoCredential(
  id: string,
  input: { label?: string | null; organization?: string; ado_project?: string | null }
) {
  return apiFetch<RepoCredential>(`/repo-credentials/${id}`, { method: "PATCH", body: JSON.stringify(input) });
}

// Replaces the stored token; the backend validates it against the credential's own org/project first.
export function reconnectRepoCredential(id: string, pat: string) {
  return apiFetch<RepoCredential>(`/repo-credentials/${id}/token`, { method: "PUT", body: JSON.stringify({ pat }) });
}

export function deleteRepoCredential(id: string) {
  return apiFetch<void>(`/repo-credentials/${id}`, { method: "DELETE" });
}

export type AdoProject = { id: string; name: string; description: string | null };

export function listCredentialProjects(credentialId: string) {
  return apiFetch<AdoProject[]>(`/repo-credentials/${credentialId}/projects`);
}

// adoProject only matters for Azure DevOps: the credential is org-wide, the project is the pick.
export function listCredentialRepos(credentialId: string, query = "", page = 1, adoProject = "") {
  const params = new URLSearchParams({
    page: String(page),
    ...(query ? { query } : {}),
    ...(adoProject ? { ado_project: adoProject } : {}),
  });
  return apiFetch<Repo[]>(`/repo-credentials/${credentialId}/repos?${params}`);
}

// repoId is "owner/repo" for GitHub or a repo GUID for Azure DevOps — never URI-encoded, the
// backend's route matches the raw path (including GitHub's literal "/").
export function listCredentialBranches(credentialId: string, repoId: string, adoProject = "") {
  const params = adoProject ? `?${new URLSearchParams({ ado_project: adoProject })}` : "";
  return apiFetch<Branch[]>(`/repo-credentials/${credentialId}/repos/${repoId}/branches${params}`);
}

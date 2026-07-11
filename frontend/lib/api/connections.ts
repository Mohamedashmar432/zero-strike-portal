import { apiFetch } from "./client";

export type Provider = "github" | "azure_devops";

export type Connection = {
  id: string;
  provider: Provider;
  account_login: string;
  connected_at: string;
};

export type Repo = {
  id: string;
  name: string;
  full_name: string;
  clone_url: string;
  private: boolean;
  default_branch: string | null;
};

export type AzureOrg = { id: string; name: string };
export type AzureProject = { id: string; name: string };

function urlSegment(provider: Provider): string {
  return provider === "azure_devops" ? "azure-devops" : "github";
}

export function listConnections() {
  return apiFetch<Connection[]>("/connections");
}

export function connectProvider(provider: Provider) {
  return apiFetch<{ authorize_url: string }>(`/connections/${urlSegment(provider)}/authorize`, {
    method: "POST",
  });
}

export function disconnectProvider(provider: Provider) {
  return apiFetch<void>(`/connections/${urlSegment(provider)}`, { method: "DELETE" });
}

export function listGithubRepos(query = "", page = 1) {
  const params = new URLSearchParams({ page: String(page), ...(query ? { query } : {}) });
  return apiFetch<Repo[]>(`/connections/github/repos?${params}`);
}

export function listAzureOrgs() {
  return apiFetch<AzureOrg[]>("/connections/azure-devops/orgs");
}

export function listAzureProjects(org: string) {
  return apiFetch<AzureProject[]>(`/connections/azure-devops/orgs/${encodeURIComponent(org)}/projects`);
}

export function listAzureRepos(org: string, project: string) {
  return apiFetch<Repo[]>(
    `/connections/azure-devops/orgs/${encodeURIComponent(org)}/projects/${encodeURIComponent(project)}/repos`
  );
}

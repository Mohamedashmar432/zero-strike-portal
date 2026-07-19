import { apiFetch } from "./client";
import type { Provider } from "./repo-credentials";

export type ProjectRepo = {
  id: string;
  project_id: string;
  provider: Provider;
  organization: string;
  ado_project: string | null;
  repo_full_name: string;
  clone_url: string;
  selected_branch: string;
  label: string | null;
  created_at: string;
};

export function listProjectRepos(projectId: string) {
  return apiFetch<ProjectRepo[]>(`/projects/${projectId}/repos`);
}

export function addProjectRepo(
  projectId: string,
  input:
    | {
        credential_id: string;
        repo_full_name: string;
        clone_url: string;
        selected_branch: string;
        label?: string;
      }
    | {
        // A public GitHub repo, connected with no credential at all (see public-repos.ts).
        public: true;
        provider: "github";
        repo_full_name: string;
        clone_url: string;
        selected_branch: string;
        label?: string;
      }
) {
  return apiFetch<ProjectRepo>(`/projects/${projectId}/repos`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateProjectRepoBranch(projectId: string, repoId: string, selectedBranch: string) {
  return apiFetch<ProjectRepo>(`/projects/${projectId}/repos/${repoId}`, {
    method: "PATCH",
    body: JSON.stringify({ selected_branch: selectedBranch }),
  });
}

export function removeProjectRepo(projectId: string, repoId: string) {
  return apiFetch<void>(`/projects/${projectId}/repos/${repoId}`, { method: "DELETE" });
}

export function reauthProjectRepo(projectId: string, repoId: string, pat: string) {
  return apiFetch<ProjectRepo>(`/projects/${projectId}/repos/${repoId}/reauth`, {
    method: "POST",
    body: JSON.stringify({ pat }),
  });
}

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
  // Repo Sync state (docs/REPO_SYNC.md), derived server-side on read.
  remote_head_sha: string | null;
  scanned_commit: string | null;
  scanned_branch: string | null;
  last_synced_at: string | null;
  active_scan_id: string | null;
  last_sync_error: string | null;
  sync_state: RepoSyncState;
};

export type RepoSyncState = "syncing" | "up_to_date" | "behind" | "error" | "never" | "unknown";
export type RepoSyncOutcome = "up_to_date" | "scan_queued" | "already_syncing";

export type RepoSyncResponse = {
  outcome: RepoSyncOutcome;
  scan_id: string | null;
  remote_head_sha: string | null;
  repo: ProjectRepo;
};

/** First 7 characters of a commit sha, for display. */
export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : "";
}

/**
 * `refetchInterval` for the repos list: poll while any repo is syncing (a queued/running scan),
 * so the row leaves its spinner on its own once the scan finishes.
 */
export function refetchWhileAnyRepoSyncing(intervalMs = 4000) {
  return (query: { state: { data?: ProjectRepo[] } }) =>
    (query.state.data ?? []).some((r) => r.sync_state === "syncing") ? intervalMs : false;
}

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
    | {
        // A private GitHub repo reached by URL + a one-off PAT (see repo-lookup.ts) — no saved
        // credential, and no organization: the backend derives it from the repo owner.
        provider: "github";
        pat: string;
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

export function syncProjectRepo(projectId: string, repoId: string, force = false) {
  return apiFetch<RepoSyncResponse>(`/projects/${projectId}/repos/${repoId}/sync`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

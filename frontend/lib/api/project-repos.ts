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
  // Auto-fix PRs as last read from the provider (distinct PRs): still open, and merged after the
  // last completed sync — the latter drives the "merged since last sync" reminder.
  autofix_open_prs: number;
  autofix_merged_since_sync: number;
};

export type PrStatusRefreshResponse = {
  checked: number;
  open: number;
  merged: number;
  closed: number;
  newly_merged: number;
  /** Sanitized provider messages; a failed PR read never fails the request. */
  errors: string[];
  repo: ProjectRepo;
};

/** "2 auto-fix PRs merged since last sync", or null when there is nothing to remind about. */
export function formatMergedPrReminder(count: number): string | null {
  if (!count || count < 1) return null;
  return `${count} auto-fix PR${count === 1 ? "" : "s"} merged since last sync`;
}

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
 * The commit to show in the Head column. A scan from a different branch than the one now selected
 * says nothing about this branch's head, so it is hidden until the branch is synced.
 */
export function headCommitForSelectedBranch(
  r: Pick<ProjectRepo, "scanned_commit" | "scanned_branch" | "selected_branch">
): string | null {
  if (!r.scanned_commit) return null;
  if (r.scanned_branch && r.scanned_branch !== r.selected_branch) return null;
  return r.scanned_commit;
}

/** Sync-finished toast text. A first scan on a branch is a baseline, not "N new". */
export function formatSyncFinishedMessage(
  name: string,
  reg: {
    has_baseline: boolean;
    baseline_branch_mismatch: boolean;
    commit: string | null;
    branch: string | null;
    new: { count: number };
    fixed: { count: number };
    reopened: { count: number };
  }
): string {
  if (!reg.has_baseline || reg.baseline_branch_mismatch) {
    const where = [reg.commit ? shortSha(reg.commit) : null, reg.branch].filter(Boolean).join(" on ");
    return `Sync of ${name} finished: Baseline established${where ? ` at ${where}` : ""} — ${reg.new.count} findings tracked`;
  }
  return `Sync of ${name} finished: ${formatSyncCounts(reg.fixed.count, reg.new.count, reg.reopened.count)}`;
}

/** "N fixed, M new, K reopened" for the sync-finished toast. */
export function formatSyncCounts(fixed: number, added: number, reopened: number): string {
  return `${fixed} fixed, ${added} new, ${reopened} reopened`;
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

/** Re-read the repo's open auto-fix PRs from the provider (Sync does this too). */
export function refreshRepoPrStatus(projectId: string, repoId: string) {
  return apiFetch<PrStatusRefreshResponse>(`/projects/${projectId}/repos/${repoId}/pr-status/refresh`, {
    method: "POST",
  });
}

export function syncProjectRepo(projectId: string, repoId: string, force = false) {
  return apiFetch<RepoSyncResponse>(`/projects/${projectId}/repos/${repoId}/sync`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

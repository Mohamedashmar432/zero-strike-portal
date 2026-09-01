import { apiFetch } from "./client";
import type { Branch, Repo } from "./repo-credentials";

// POST, not GET: the PAT goes in the body so it never reaches a URL or an access log.
export function lookupGithubRepo(repoFullName: string, pat: string) {
  return apiFetch<{ repo: Repo; branches: Branch[] }>("/repo-lookup/github", {
    method: "POST",
    body: JSON.stringify({ repo_full_name: repoFullName, pat }),
  });
}

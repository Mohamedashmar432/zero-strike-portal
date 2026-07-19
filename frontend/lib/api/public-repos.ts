import { apiFetch } from "./client";
import type { Branch, Repo } from "./repo-credentials";

// Accepts "owner/repo" or a full GitHub URL (with or without .git/trailing slash).
export function parseGithubOwnerRepo(input: string): { owner: string; repo: string } | null {
  const trimmed = input
    .trim()
    .replace(/\.git$/, "")
    .replace(/\/$/, "");
  const urlMatch = trimmed.match(/^(?:https?:\/\/)?(?:www\.)?github\.com\/([^/\s]+)\/([^/\s]+)$/i);
  const bareMatch = trimmed.match(/^([^/\s]+)\/([^/\s]+)$/);
  const match = urlMatch ?? bareMatch;
  return match ? { owner: match[1], repo: match[2] } : null;
}

export function getPublicGithubRepo(owner: string, repo: string) {
  return apiFetch<Repo>(`/public-repos/github/${owner}/${repo}`);
}

export function listPublicGithubBranches(owner: string, repo: string) {
  return apiFetch<Branch[]>(`/public-repos/github/${owner}/${repo}/branches`);
}

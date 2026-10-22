/**
 * A readable name for a scanned repository, from whatever the scanner or a connection recorded: an https
 * clone URL, an scp-style `git@host:org/repo.git`, or a local path. Mirrors `repo_identity` in
 * backend/app/services/pdf_report_service.py (the PDF) so the portal and the report name a repo the same way.
 *
 *   https://dev.azure.com/acme/Platform/_git/Visitor%20management -> name "Visitor management", owner "acme / Platform"
 *   https://github.com/octocat/hello-world.git                    -> name "hello-world",        owner "octocat"
 */
export type RepoIdentity = { name: string; owner: string | null };

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    return segment; // a stray "%" must not break a page that only wanted a label
  }
}

export function repoIdentity(source: string | null | undefined): RepoIdentity | null {
  let raw = (source ?? "").trim();
  if (!raw) return null;

  if (raw.includes("://")) {
    try {
      raw = new URL(raw).pathname;
    } catch {
      raw = raw.slice(raw.indexOf("://") + 3).split("/").slice(1).join("/");
    }
  } else if (/^[\w.-]+@[\w.-]+:/.test(raw)) {
    raw = raw.slice(raw.indexOf(":") + 1); // git@github.com:org/repo.git
  }

  const parts = raw
    .split(/[\\/]/)
    .filter(Boolean)
    .map(decode);
  if (!parts.length) return null;

  // Azure DevOps: /{org}/{project}/_git/{repo}. Everything before `_git` owns the repo.
  const git = parts.indexOf("_git");
  const nameIndex = git >= 0 && parts[git + 1] ? git + 1 : parts.length - 1;
  const ownerParts = git >= 0 && parts[git + 1] ? parts.slice(0, git) : parts.slice(0, -1);

  const name = parts[nameIndex].replace(/\.git$/i, "");
  if (!name) return null;
  return { name, owner: ownerParts.length ? ownerParts.join(" / ") : null };
}

/** Just the name, for places that only have room for one line. Falls back to the raw text, never to nothing. */
export function repoName(source: string | null | undefined): string {
  return repoIdentity(source)?.name ?? (source?.trim() || "—");
}

/** Only http(s) URLs become links: a scanner-supplied value must never turn into a `javascript:` href. */
export function safeRepoHref(source: string | null | undefined): string | null {
  const raw = (source ?? "").trim();
  return /^https?:\/\//i.test(raw) ? raw : null;
}

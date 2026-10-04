import { shortSha } from "@/lib/api/project-repos";
import type { FixStatus } from "@/lib/api/vulnerabilities";

export const FIX_STATUS_LABELS: Record<FixStatus, string> = {
  open: "Open",
  reopened: "Reopened",
  fixed: "Fixed (no longer detected)",
  dismissed: "Dismissed",
};

// Shown wherever "Fixed" appears: the fingerprint is what stopped matching, not a human decision,
// so an edit to the vulnerable line (or a renamed config file) reads as fixed + new.
export const FIXED_TOOLTIP =
  "No longer detected by the scanner. Editing a vulnerable line that is still vulnerable, or renaming a config file, can also read as fixed plus a new finding.";

/** `branch@sha7`, falling back to whichever half exists, or an em dash for legacy rows. */
export function CommitRef({
  commit,
  branch,
  className,
}: {
  commit: string | null | undefined;
  branch?: string | null;
  className?: string;
}) {
  if (!commit && !branch) return <span className="text-xs text-muted-foreground">—</span>;
  const sha = shortSha(commit);
  return (
    <span className={className ?? "font-mono text-xs"} title={commit ?? undefined}>
      {branch ? `${branch}${sha ? "@" : ""}` : ""}
      {sha}
    </span>
  );
}

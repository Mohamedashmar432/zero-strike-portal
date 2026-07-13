import type { Repo } from "@/lib/api/repo-credentials";

export function RepoPickerList({
  repos,
  isLoading,
  isError,
  onSelect,
}: {
  repos: Repo[] | undefined;
  isLoading: boolean;
  isError: boolean;
  onSelect: (repo: Repo) => void;
}) {
  return (
    <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-border p-1">
      {isLoading ? (
        <p className="p-2 text-sm text-muted-foreground">Loading…</p>
      ) : isError ? (
        <p className="p-2 text-sm text-destructive">Couldn&apos;t load repos — check the credential&apos;s PAT is still valid.</p>
      ) : repos?.length ? (
        repos.map((r) => (
          <button
            key={r.id}
            type="button"
            className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
            onClick={() => onSelect(r)}
          >
            {r.full_name}
          </button>
        ))
      ) : (
        <p className="p-2 text-sm text-muted-foreground">No repos found.</p>
      )}
    </div>
  );
}

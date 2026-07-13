import { Button } from "@/components/ui/button";
import type { Repo } from "@/lib/api/repo-credentials";

export function SelectedRepoSummary({ repo, onChange }: { repo: Repo; onChange: () => void }) {
  return (
    <div className="flex items-center justify-between rounded-md border border-border px-3 py-2 text-sm">
      <span className="truncate font-mono">{repo.full_name}</span>
      <Button type="button" size="sm" variant="ghost" onClick={onChange}>
        Change
      </Button>
    </div>
  );
}

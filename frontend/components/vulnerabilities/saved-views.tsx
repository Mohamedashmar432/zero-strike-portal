"use client";

import { Bookmark, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MAX_SAVED_VIEWS, loadViews, saveViews, type SavedView } from "@/lib/vulnerability-filters";

/**
 * Named filter sets, kept in this browser (localStorage, keyed by project). Never shared and never
 * sent anywhere: a view is only a query string for this page, so applying one is just a navigation.
 */
export function SavedViews({
  projectId,
  currentQuery,
  onApply,
}: {
  projectId: string;
  /** Filters + sort of the page right now, without view or page. */
  currentQuery: string;
  onApply: (query: string) => void;
}) {
  const [views, setViews] = useState<SavedView[]>([]);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  // localStorage only exists in the browser; reading it during render would mismatch the server HTML.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setViews(loadViews(projectId));
  }, [projectId]);

  function persist(next: SavedView[]) {
    setViews(next);
    saveViews(projectId, next);
  }

  function add() {
    const trimmed = name.trim();
    if (!trimmed || !currentQuery) return;
    persist([{ id: `${Date.now()}`, name: trimmed.slice(0, 40), query: currentQuery }, ...views].slice(0, MAX_SAVED_VIEWS));
    setName("");
    setNaming(false);
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Saved views">
      <span className="legend flex items-center gap-1 text-muted-foreground">
        <Bookmark className="size-3" aria-hidden="true" /> Views
      </span>
      {views.length === 0 && !naming && <span className="text-xs text-muted-foreground">None saved</span>}
      {views.map((v) => (
        <span key={v.id} className="inline-flex h-6 items-center rounded-sm border border-border bg-card text-[11px]">
          <button
            type="button"
            onClick={() => onApply(v.query)}
            className="h-full cursor-pointer rounded-l-sm px-2 font-mono hover:text-signal focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {v.name}
          </button>
          <button
            type="button"
            aria-label={`Delete saved view ${v.name}`}
            onClick={() => persist(views.filter((x) => x.id !== v.id))}
            className="h-full cursor-pointer rounded-r-sm px-1 text-muted-foreground hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <X className="size-3" aria-hidden="true" />
          </button>
        </span>
      ))}
      {naming ? (
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            add();
          }}
        >
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setNaming(false)}
            aria-label="Name for this view"
            placeholder="View name"
            className="h-6 w-36 text-xs"
            maxLength={40}
          />
          <Button type="submit" size="xs" disabled={!name.trim()}>
            Save
          </Button>
          <Button type="button" size="xs" variant="ghost" onClick={() => setNaming(false)}>
            Cancel
          </Button>
        </form>
      ) : (
        <Button
          size="xs"
          variant="outline"
          disabled={!currentQuery || views.length >= MAX_SAVED_VIEWS}
          title={currentQuery ? undefined : "Choose a filter or sort first"}
          onClick={() => setNaming(true)}
        >
          Save current
        </Button>
      )}
    </div>
  );
}

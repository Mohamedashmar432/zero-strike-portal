"use client";

/**
 * The master pane: every proposal in the scan, searchable and filterable, with keyboard navigation.
 * The stacked-accordion layout this replaces was unusable past ~20 proposals — you had to scroll
 * past every expanded diff to reach the next finding.
 */

import { MessageSquare, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { FixReviewStateBadge } from "@/components/auto-fix/fix-review-state-badge";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Input } from "@/components/ui/input";
import type { AiFixProposal, FixReviewState } from "@/lib/api/auto-fix";
import type { Severity } from "@/lib/api/findings";
import { cn } from "@/lib/utils";
import { confidenceTone, FALLBACK_THRESHOLD } from "./fix-actions";

/** The buckets the summary StatCards use, so clicking through from a stat means the same thing. */
type Bucket = "all" | "ai_fixable" | "needs_review_on_fix" | "cannot_fix" | "pr_created";

const BUCKET_LABEL: Record<Bucket, string> = {
  all: "All",
  ai_fixable: "AI can fix",
  needs_review_on_fix: "Needs review",
  cannot_fix: "Manual",
  pr_created: "PR open",
};

const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];
const SEVERITY_RANK = new Map(SEVERITY_ORDER.map((s, i) => [s, SEVERITY_ORDER.length - i]));

function bucketOf(p: AiFixProposal, threshold: number): Bucket {
  if (p.pr_url) return "pr_created";
  if (!p.can_fix) return "cannot_fix";
  return p.confidence_score >= threshold ? "ai_fixable" : "needs_review_on_fix";
}

/** Severity desc, then file, then line — the same total order the backend brief uses, so the list
 * and a downloaded brief read in the same sequence.
 *
 * Exported because the workspace picks its DEFAULT selection with it: using the raw API order there
 * instead landed the reviewer on whatever the server returned first (in practice the lowest-severity
 * finding) while the list showed criticals at the top. One comparator, one order. */
export function compareProposals(a: AiFixProposal, b: AiFixProposal): number {
  const sev = (SEVERITY_RANK.get(b.finding_severity as Severity) ?? 0) - (SEVERITY_RANK.get(a.finding_severity as Severity) ?? 0);
  if (sev !== 0) return sev;
  const file = (a.finding_file ?? "").localeCompare(b.finding_file ?? "");
  if (file !== 0) return file;
  return (a.finding_start_line ?? 0) - (b.finding_start_line ?? 0);
}

export function FixProposalList({
  proposals,
  selectedId,
  onSelect,
  commentCounts,
  threshold = FALLBACK_THRESHOLD,
}: {
  proposals: AiFixProposal[];
  selectedId: string | null;
  onSelect: (findingId: string) => void;
  commentCounts: Map<string, number>;
  /** Effective bar from AutoFixSummary.confidence_threshold. */
  threshold?: number;
}) {
  const [query, setQuery] = useState("");
  const [bucket, setBucket] = useState<Bucket>("all");
  const [severities, setSeverities] = useState<Set<Severity>>(new Set());
  const listRef = useRef<HTMLUListElement>(null);

  const counts = useMemo(() => {
    const out: Record<Bucket, number> = { all: proposals.length, ai_fixable: 0, needs_review_on_fix: 0, cannot_fix: 0, pr_created: 0 };
    for (const p of proposals) out[bucketOf(p, threshold)] += 1;
    return out;
  }, [proposals, threshold]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return proposals
      .filter((p) => {
        if (bucket !== "all" && bucketOf(p, threshold) !== bucket) return false;
        if (severities.size && !severities.has(p.finding_severity as Severity)) return false;
        if (!q) return true;
        return (
          (p.finding_rule_name ?? "").toLowerCase().includes(q) ||
          (p.finding_file ?? "").toLowerCase().includes(q) ||
          (p.explanation ?? "").toLowerCase().includes(q)
        );
      })
      .sort(compareProposals);
  }, [proposals, query, bucket, severities, threshold]);

  const toggleSeverity = (s: Severity) =>
    setSeverities((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });

  // j/k and arrows move the selection, matching the muscle memory of every other review tool.
  // Handled on the list so it only fires when the list (not the search box) has focus.
  const onKeyDown = (e: React.KeyboardEvent) => {
    const step = e.key === "j" || e.key === "ArrowDown" ? 1 : e.key === "k" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const idx = visible.findIndex((p) => p.finding_id === selectedId);
    const next = visible[Math.min(visible.length - 1, Math.max(0, (idx === -1 ? 0 : idx) + step))];
    if (next) {
      onSelect(next.finding_id);
      // Optional-call: keeping the row visible is a nicety, and it must never break navigation
      // where scrollIntoView is missing (jsdom, older embedded webviews).
      listRef.current
        ?.querySelector(`[data-finding-id="${next.finding_id}"]`)
        ?.scrollIntoView?.({ block: "nearest" });
    }
  };

  const availableSeverities = SEVERITY_ORDER.filter((s) =>
    proposals.some((p) => p.finding_severity === s)
  );

  return (
    <div className="flex min-h-0 flex-col rounded-lg border">
      <div className="space-y-2 border-b p-2">
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search rule, file, or explanation…"
            aria-label="Search fix proposals"
            className="h-8 pl-8"
          />
        </div>

        <div className="flex flex-wrap gap-1">
          {(Object.keys(BUCKET_LABEL) as Bucket[]).map((b) => (
            <button
              key={b}
              type="button"
              onClick={() => setBucket(b)}
              aria-pressed={bucket === b}
              className={cn(
                "rounded-full border px-2 py-0.5 text-xs transition-colors",
                bucket === b
                  ? "border-brand bg-brand/10 text-brand"
                  : "text-muted-foreground hover:bg-muted/50"
              )}
            >
              {BUCKET_LABEL[b]} {counts[b]}
            </button>
          ))}
        </div>

        {availableSeverities.length > 1 && (
          <div className="flex flex-wrap gap-1">
            {availableSeverities.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => toggleSeverity(s)}
                aria-pressed={severities.has(s)}
                className={cn(
                  "rounded-full border px-2 py-0.5 text-xs uppercase transition-colors",
                  severities.has(s) ? "border-brand bg-brand/10 text-brand" : "text-muted-foreground hover:bg-muted/50"
                )}
              >
                {s}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Plain overflow-y-auto rather than a scroll-area primitive — native scrolling keeps the
          keyboard scrollIntoView above working and needs no extra dependency. */}
      <ul
        ref={listRef}
        onKeyDown={onKeyDown}
        // biome-ignore lint/a11y/noNoninteractiveTabindex: the list owns j/k navigation, so it must be focusable.
        tabIndex={0}
        aria-label="Fix proposals"
        className="min-h-0 flex-1 overflow-y-auto outline-none lg:max-h-[70vh]"
      >
        {visible.length === 0 && (
          <li className="p-4 text-sm text-muted-foreground">
            No proposals match these filters.
          </li>
        )}
        {visible.map((p) => {
          const selected = p.finding_id === selectedId;
          const comments = commentCounts.get(p.finding_id) ?? 0;
          return (
            <li key={p.id} data-finding-id={p.finding_id}>
              <button
                type="button"
                onClick={() => onSelect(p.finding_id)}
                aria-current={selected}
                className={cn(
                  "w-full space-y-1 border-b px-3 py-2 text-left transition-colors last:border-b-0",
                  selected ? "bg-brand/10" : "hover:bg-muted/40",
                  p.review_state === "dismissed" && "opacity-60"
                )}
              >
                <div className="flex items-center gap-2">
                  {p.finding_severity && <SeverityBadge severity={p.finding_severity} />}
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">
                    {p.finding_rule_name ?? "Finding"}
                  </span>
                  {p.can_fix && (
                    <span className={cn("shrink-0 font-mono text-xs", confidenceTone(p.confidence_score, threshold))}>
                      {Math.round(p.confidence_score)}%
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
                    {p.finding_file ?? "—"}
                    {p.finding_start_line ? `:${p.finding_start_line}` : ""}
                  </span>
                  {comments > 0 && (
                    <span className="flex shrink-0 items-center gap-0.5 text-xs text-brand">
                      <MessageSquare className="size-3" /> {comments}
                    </span>
                  )}
                  <FixReviewStateBadge state={p.review_state as FixReviewState} />
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CircleCheck,
  CircleX,
  GitBranch,
  GitPullRequest,
  History,
  ShieldCheck,
  Sparkles,
  TriangleAlert,
} from "lucide-react";
import type { ActivityEvent } from "@/lib/api/auto-fix";
import { getScanAutoFixActivity } from "@/lib/api/auto-fix";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

/** Icon + tone per audited action. Keys are the audit_service action strings the backend writes —
 * an unrecognized action still renders, just with the neutral default. */
const STYLE: Record<string, { icon: typeof History; tone: string }> = {
  "AI Fix Proposals Generated": { icon: Sparkles, tone: "text-brand" },
  "AI Fix Proposals Failed": { icon: TriangleAlert, tone: "text-severity-critical" },
  "AI Fix Approved": { icon: CircleCheck, tone: "text-emerald-500" },
  "AI Fix Proposal Dismissed": { icon: CircleX, tone: "text-muted-foreground" },
  "AI Fix Validation Passed": { icon: ShieldCheck, tone: "text-emerald-500" },
  "AI Fix Branch Pushed": { icon: GitBranch, tone: "text-brand" },
  "AI Fix PR Opened": { icon: GitPullRequest, tone: "text-emerald-500" },
};

/** The few metadata keys worth surfacing, in a fixed order so the line reads consistently. */
const META_KEYS: [string, (v: unknown) => string][] = [
  ["findings", (v) => `${v} finding(s)`],
  ["fixable", (v) => `${v} fixable`],
  ["branch", (v) => `branch ${v}`],
  ["pr_number", (v) => `PR #${v}`],
  ["error", (v) => String(v)],
];

function metaSummary(metadata: Record<string, unknown>): string {
  return META_KEYS.filter(([k]) => metadata?.[k] !== undefined && metadata?.[k] !== null)
    .map(([k, fmt]) => fmt(metadata[k]))
    .join(" · ");
}

function Event({ event }: { event: ActivityEvent }) {
  const { icon: Icon, tone } = STYLE[event.action] ?? { icon: History, tone: "text-muted-foreground" };
  const meta = metaSummary((event.metadata ?? {}) as Record<string, unknown>);
  const prUrl = (event.metadata as Record<string, unknown> | undefined)?.pr_url;

  return (
    <li className="flex gap-3">
      <Icon className={cn("mt-0.5 size-4 shrink-0", tone)} aria-hidden />
      <div className="min-w-0 space-y-0.5">
        <p className="text-sm">
          <span className="font-medium">{event.action}</span>
          {event.actor_name && <span className="text-muted-foreground"> by {event.actor_name}</span>}
        </p>
        <p className="text-xs text-muted-foreground">
          <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString()}</time>
          {meta && ` · ${meta}`}
        </p>
        {typeof prUrl === "string" && (
          <a
            href={prUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-brand underline underline-offset-2"
          >
            View pull request
          </a>
        )}
      </div>
    </li>
  );
}

/**
 * Team-visible timeline of auto-fix actions, newest last, sourced from the audit log.
 *
 * `findingId` narrows it to one finding (the detail pane's Activity tab); without it the whole scan
 * is shown (the section header). Events with no target finding — job-level ones like "Proposals
 * Generated" — are always kept, since they explain how the proposal came to exist.
 */
export function ActivityTimeline({
  scanId,
  findingId,
  defaultOpen = false,
}: {
  scanId: string;
  findingId?: string;
  defaultOpen?: boolean;
}) {
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.ai.autofix.activity(scanId),
    queryFn: () => getScanAutoFixActivity(scanId),
  });

  const all = data?.items ?? [];
  const items = findingId
    ? all.filter((e) => {
        const meta = (e.metadata ?? {}) as Record<string, unknown>;
        // Job-level events carry no finding_id — keep them as context for every finding.
        if (e.target_type === "remediation_job") return true;
        return meta.finding_id === findingId;
      })
    : all;

  if (isLoading && defaultOpen) {
    return <p className="text-sm text-muted-foreground">Loading activity…</p>;
  }
  if (!items.length) {
    return defaultOpen ? (
      <p className="text-sm text-muted-foreground">No activity recorded for this fix yet.</p>
    ) : null;
  }

  // Flat list when it's the pane's own tab; collapsed <details> when it sits inside a busy header.
  if (defaultOpen) {
    return (
      <ol className="space-y-3">
        {items.map((e, i) => (
          <Event key={`${e.action}-${e.created_at}-${i}`} event={e} />
        ))}
      </ol>
    );
  }

  return (
    <details className="rounded-lg border bg-muted/20 p-4">
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium">
        <History className="size-4" /> Activity ({items.length})
      </summary>
      <ol className="mt-3 space-y-3">
        {items.map((e, i) => (
          <Event key={`${e.action}-${e.created_at}-${i}`} event={e} />
        ))}
      </ol>
    </details>
  );
}

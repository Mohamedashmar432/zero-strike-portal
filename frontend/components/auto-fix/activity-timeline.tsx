"use client";

import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";
import { getScanAutoFixActivity } from "@/lib/api/auto-fix";
import { queryKeys } from "@/lib/api/query-keys";

/** Team-visible timeline of auto-fix actions on this scan (proposed, approved, PR opened, …).
 * Collapsed by default via native <details>. Hidden until there's at least one event. */
export function ActivityTimeline({ scanId }: { scanId: string }) {
  const { data } = useQuery({
    queryKey: queryKeys.ai.autofix.activity(scanId),
    queryFn: () => getScanAutoFixActivity(scanId),
  });

  const items = data?.items ?? [];
  if (!items.length) return null;

  return (
    <details className="rounded-lg border bg-muted/20 p-4">
      <summary className="flex cursor-pointer items-center gap-2 text-sm font-medium">
        <History className="size-4" /> Activity ({items.length})
      </summary>
      <ol className="mt-3 space-y-2 border-l pl-4">
        {items.map((e, i) => (
          <li key={i} className="text-sm">
            <span className="font-medium">{e.action}</span>
            {e.actor_name ? <span className="text-muted-foreground"> · {e.actor_name}</span> : null}
            <span className="ml-2 text-xs text-muted-foreground">
              {new Date(e.created_at).toLocaleString()}
            </span>
          </li>
        ))}
      </ol>
    </details>
  );
}

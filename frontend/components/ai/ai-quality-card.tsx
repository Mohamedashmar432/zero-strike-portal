"use client";

import { useQuery } from "@tanstack/react-query";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getPortalAiQuality } from "@/lib/api/ai";

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);

export function AiQualityCard() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ["ai-quality", 30],
    queryFn: () => getPortalAiQuality(30),
  });

  const rows: [string, string][] = data
    ? [
        ["Fixes drafted", `${data.drafted} of ${data.proposals}`],
        ["Accepted by a reviewer", pct(data.acceptance_rate)],
        ["Dismissed", pct(data.dismissal_rate)],
        ["Re-scan cleared the finding", pct(data.rescan_cleared_rate)],
        ["PRs merged", String(data.merged)],
        [
          "Critic verdicts",
          Object.entries(data.critic_verdicts).map(([k, v]) => `${k} ${v}`).join(" · ") || "—",
        ],
        ["LLM calls per finding", data.avg_calls_per_finding?.toString() ?? "—"],
        ["Tokens per finding", data.avg_tokens_per_finding?.toLocaleString() ?? "—"],
        [
          "Cost per finding",
          data.avg_cost_usd_per_finding === null ? "—" : `$${data.avg_cost_usd_per_finding.toFixed(4)}`,
        ],
        ["Prompt cache hit rate", pct(data.cache_hit_rate)],
      ]
    : [];

  return (
    <Card>
      <CardHeader>
        <CardTitle>Auto-Fix quality · last 30 days</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
        {isError && <p className="text-sm text-destructive">Could not load quality metrics.</p>}
        {data && (
          <dl className="grid grid-cols-1 gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
            {rows.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-medium tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="mt-3 text-xs text-muted-foreground">
          Per-finding cost and cache figures count only calls made after attribution shipped.
        </p>
      </CardContent>
    </Card>
  );
}

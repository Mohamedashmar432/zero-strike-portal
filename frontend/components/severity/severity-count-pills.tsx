import { cn } from "@/lib/utils";
import type { SeverityCounts } from "@/lib/api/dashboard";
import type { Severity } from "@/lib/api/findings";

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

export const SEVERITY_LETTER: Record<Severity, string> = {
  critical: "C",
  high: "H",
  medium: "M",
  low: "L",
  info: "I",
};

export const SEVERITY_PILL_CLASS: Record<Severity, string> = {
  critical: "bg-severity-critical/15 text-severity-critical",
  high: "bg-severity-high/15 text-severity-high",
  medium: "bg-severity-medium/15 text-severity-medium",
  low: "bg-severity-low/15 text-severity-low",
  info: "bg-severity-info/15 text-severity-info",
};

export function SeverityCountPills({ counts }: { counts: SeverityCounts }) {
  const nonZero = SEVERITY_ORDER.filter((severity) => counts[severity] > 0);
  if (nonZero.length === 0) return <span className="text-xs text-muted-foreground">No findings</span>;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {nonZero.map((severity) => (
        <span
          key={severity}
          className={cn(
            "inline-flex min-w-[2.25rem] items-center justify-center rounded-full px-2 py-0.5 font-mono text-xs font-semibold",
            SEVERITY_PILL_CLASS[severity]
          )}
        >
          {counts[severity]} {SEVERITY_LETTER[severity]}
        </span>
      ))}
    </div>
  );
}

// Not a real risk-scoring model — just buckets a project/repo's latest severity
// counts into the mockup's three status tiers.
export function projectRiskStatus(counts: SeverityCounts) {
  if (counts.critical > 0) return { label: "At Risk", className: SEVERITY_PILL_CLASS.critical };
  if (counts.high > 0) return { label: "Action Needed", className: SEVERITY_PILL_CLASS.high };
  return { label: "Stable", className: "bg-status-success/15 text-status-success" };
}

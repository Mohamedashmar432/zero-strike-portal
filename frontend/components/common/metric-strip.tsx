import type { ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

export type MetricTone = "default" | "signal" | "critical" | "high" | "medium" | "low";

const TONE_VALUE: Record<MetricTone, string> = {
  default: "text-foreground",
  signal: "text-signal",
  critical: "text-severity-critical",
  high: "text-severity-high",
  medium: "text-severity-medium",
  low: "text-severity-low",
};

const TONE_TICK: Record<MetricTone, string> = {
  default: "bg-muted-foreground/30",
  signal: "bg-signal",
  critical: "bg-severity-critical",
  high: "bg-severity-high",
  medium: "bg-severity-medium",
  low: "bg-severity-low",
};

export type Metric = {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: MetricTone;
  /** Optional slot under the value — a spectrum bar, a delta, a sparkline. */
  meter?: ReactNode;
};

/**
 * The instrument strip: one bordered rack unit divided by hairlines.
 *
 * This replaces the row of four floating KPI cards, which is the most
 * recognisable generated-dashboard shape there is. A strip is also honestly
 * better here: the numbers are a *set* that gets compared left-to-right, and
 * four separate bordered boxes with their own shadows visually argue they're
 * four unrelated things. One unit, internal dividers, shared baseline.
 *
 * Each cell carries a colored tick at its top-left corner — enough to encode
 * severity without painting a whole card red.
 */
export function MetricStrip({
  metrics,
  isLoading,
  className,
}: {
  metrics: Metric[];
  isLoading?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "grid grid-cols-2 overflow-hidden rounded-lg border border-border bg-card lg:grid-cols-4",
        className
      )}
    >
      {metrics.map((metric, i) => {
        const tone = metric.tone ?? "default";
        return (
          <div
            key={metric.label}
            className={cn(
              "relative flex min-w-0 flex-col gap-2 px-4 py-3.5",
              // Hairlines only *between* cells, never against the strip's own
              // edge. Scoped with max-lg/lg rather than adding then zeroing a
              // border, since a custom utility vs. `border-t-0` would be decided
              // by stylesheet order.
              i % 2 === 1 && "max-lg:hairline-x",
              i >= 2 && "max-lg:hairline-y",
              i % 4 !== 0 && "lg:hairline-x"
            )}
          >
            {/* Corner tick — the cell's severity register mark. */}
            <span className={cn("absolute left-0 top-0 h-6 w-0.5", TONE_TICK[tone])} />

            <span className="legend text-muted-foreground">{metric.label}</span>

            {isLoading ? (
              <Skeleton className="h-8 w-16" />
            ) : (
              <span className={cn("readout text-3xl leading-none", TONE_VALUE[tone])}>
                {metric.value}
              </span>
            )}

            {metric.meter}

            {metric.hint && (
              <span className="line-clamp-2 text-[11px] leading-tight text-muted-foreground">
                {metric.hint}
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

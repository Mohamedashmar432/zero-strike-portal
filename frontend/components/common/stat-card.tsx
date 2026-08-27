import type { ReactNode } from "react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Single metric panel. Same visual language as a MetricStrip cell (mono legend,
 * mono readout, corner tick) for pages that need one metric standalone rather
 * than a comparable set.
 *
 * Prefer `MetricStrip` whenever you have 2+ related metrics — a row of these
 * reproduces exactly the floating-KPI-card look this redesign removed.
 */
export function StatCard({
  label,
  value,
  caption,
  valueClassName,
  pillClassName,
  size = "lg",
  isLoading,
}: {
  label: string;
  value: ReactNode;
  caption?: string;
  valueClassName?: string;
  pillClassName?: string;
  size?: "sm" | "lg";
  isLoading?: boolean;
}) {
  return (
    <div className="relative flex flex-col gap-2 rounded-lg border border-border bg-card px-4 py-3.5 transition-colors duration-200 hover:border-muted-foreground/30">
      <span className="absolute left-0 top-0 h-6 w-0.5 bg-muted-foreground/30" />
      <span className="legend text-muted-foreground">{label}</span>

      {isLoading ? (
        <Skeleton className="h-8 w-16" />
      ) : (
        <span
          className={cn(
            "readout leading-none",
            size === "lg" ? "text-3xl" : "text-2xl",
            valueClassName
          )}
        >
          {value}
        </span>
      )}

      {caption &&
        (pillClassName ? (
          <span
            className={cn(
              "legend inline-block w-fit rounded-sm px-1.5 py-0.5",
              pillClassName
            )}
          >
            {caption}
          </span>
        ) : (
          <p className="text-[11px] leading-tight text-muted-foreground">{caption}</p>
        ))}
    </div>
  );
}

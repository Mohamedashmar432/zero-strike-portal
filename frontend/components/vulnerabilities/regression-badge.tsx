import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import type { RegressionState } from "@/lib/api/vulnerabilities";

export const REGRESSION_STATE_LABELS: Record<RegressionState, string> = {
  new: "New",
  reopened: "Reopened",
  fixed: "Fixed",
  unchanged: "Unchanged",
};

// Regression is a first-class outcome, not a filter -- give it the same left-edge-tag
// treatment as severity/status badges so it reads consistently in the work queue and never
// relies on color alone (label text is always rendered alongside the tint).
const regressionBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-sm border-l-2 py-0.5 pr-1.5 pl-1.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] leading-none",
  {
    variants: {
      state: {
        new: "border-severity-high bg-severity-high-tint text-severity-high",
        reopened: "border-severity-critical bg-severity-critical-tint text-severity-critical",
        fixed: "border-status-success bg-status-success-tint text-status-success",
        unchanged: "border-muted-foreground/40 bg-muted text-muted-foreground",
      },
    },
    defaultVariants: { state: "unchanged" },
  }
);

type RegressionBadgeProps = VariantProps<typeof regressionBadgeVariants> & {
  state: RegressionState | null;
  className?: string;
};

export function RegressionBadge({ state, className }: RegressionBadgeProps) {
  if (!state) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span className={cn(regressionBadgeVariants({ state }), className)}>
      {REGRESSION_STATE_LABELS[state]}
    </span>
  );
}

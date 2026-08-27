import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/**
 * Severity tag. A solid 2px left edge in the tier color plus a faint tint —
 * a terminal-block marker rather than a soft rounded chip. The hard edge is
 * what makes the tier readable at a glance in a dense list, and it means
 * severity is encoded by *position and shape* as well as hue, so the badge
 * still parses for red/green colorblind readers.
 */
const severityBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-sm border-l-2 py-0.5 pr-1.5 pl-1.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] leading-none",
  {
    variants: {
      severity: {
        critical: "border-severity-critical bg-severity-critical-tint text-severity-critical",
        high: "border-severity-high bg-severity-high-tint text-severity-high",
        medium: "border-severity-medium bg-severity-medium-tint text-severity-medium",
        low: "border-severity-low bg-severity-low-tint text-severity-low",
        info: "border-severity-info bg-severity-info-tint text-severity-info",
      },
    },
    defaultVariants: { severity: "info" },
  }
);

type SeverityBadgeProps = VariantProps<typeof severityBadgeVariants> & {
  className?: string;
};

export function SeverityBadge({ severity, className }: SeverityBadgeProps) {
  return <span className={cn(severityBadgeVariants({ severity }), className)}>{severity}</span>;
}

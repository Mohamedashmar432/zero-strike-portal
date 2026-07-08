import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const severityBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide",
  {
    variants: {
      severity: {
        critical: "bg-severity-critical/15 text-severity-critical",
        high: "bg-severity-high/15 text-severity-high",
        medium: "bg-severity-medium/15 text-severity-medium",
        low: "bg-severity-low/15 text-severity-low",
        info: "bg-severity-info/15 text-severity-info",
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

import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const scanStatusBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide",
  {
    variants: {
      status: {
        pending: "bg-severity-info/15 text-severity-info",
        queued: "bg-severity-medium/15 text-severity-medium",
        running: "bg-status-progress/15 text-status-progress",
        completed: "bg-status-success/15 text-status-success",
        failed: "bg-severity-critical/15 text-severity-critical",
      },
    },
    defaultVariants: { status: "pending" },
  }
);

type ScanStatusBadgeProps = VariantProps<typeof scanStatusBadgeVariants> & {
  className?: string;
};

export function ScanStatusBadge({ status = "pending", className }: ScanStatusBadgeProps) {
  return (
    <span className={cn(scanStatusBadgeVariants({ status }), className)}>
      {status === "running" && <span className="size-1.5 animate-pulse rounded-sm bg-current" />}
      {status}
    </span>
  );
}

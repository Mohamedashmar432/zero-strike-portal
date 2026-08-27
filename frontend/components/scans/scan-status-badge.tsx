import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const scanStatusBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-sm border-l-2 py-0.5 pr-1.5 pl-1.5 font-mono text-[11px] font-semibold uppercase tracking-[0.08em] leading-none",
  {
    variants: {
      status: {
        pending: "border-severity-info bg-severity-info-tint text-severity-info",
        queued: "border-severity-medium bg-severity-medium-tint text-severity-medium",
        running: "border-status-progress bg-status-progress-tint text-status-progress",
        completed: "border-status-success bg-status-success-tint text-status-success",
        failed: "border-severity-critical bg-severity-critical-tint text-severity-critical",
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
      {/* Running gets a breathing halo rather than a spinner — a spinner in a
          table cell implies "this row is loading", which is a different fact. */}
      {status === "running" && <span className="pulse-signal size-1.5 rounded-full bg-current" />}
      {status}
    </span>
  );
}

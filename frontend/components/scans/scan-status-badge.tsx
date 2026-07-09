import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const scanStatusBadgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide",
  {
    variants: {
      status: {
        pending: "bg-slate-500/15 text-slate-400",
        running: "bg-sky-500/15 text-sky-400",
        completed: "bg-emerald-500/15 text-emerald-400",
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
      {status === "running" && <span className="size-1.5 animate-pulse rounded-full bg-current" />}
      {status}
    </span>
  );
}

import { cva, type VariantProps } from "class-variance-authority";
import { CONTROL_STATUS_LABEL, type ControlStatus } from "@/lib/api/compliance";
import { cn } from "@/lib/utils";

// Same shape/formula as severity-badge (bg-X/15 text-X). needs_manual_review deliberately
// uses the neutral info token, not a warning colour: it is not a bad result, it's a control
// this tool cannot speak to.
const controlStatusVariants = cva(
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide",
  {
    variants: {
      status: {
        pass: "bg-status-success/15 text-status-success",
        fail: "bg-severity-critical/15 text-severity-critical",
        partial: "bg-severity-medium/15 text-severity-medium",
        not_applicable: "bg-muted text-muted-foreground",
        needs_manual_review: "bg-severity-info/15 text-severity-info",
      },
    },
    defaultVariants: { status: "needs_manual_review" },
  }
);

type ControlStatusBadgeProps = VariantProps<typeof controlStatusVariants> & {
  className?: string;
};

export function ControlStatusBadge({ status, className }: ControlStatusBadgeProps) {
  return (
    <span className={cn(controlStatusVariants({ status }), className)}>
      {CONTROL_STATUS_LABEL[(status ?? "needs_manual_review") as ControlStatus]}
    </span>
  );
}

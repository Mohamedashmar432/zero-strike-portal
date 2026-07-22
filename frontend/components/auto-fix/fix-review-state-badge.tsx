import type { FixReviewState } from "@/lib/api/auto-fix";
import { cn } from "@/lib/utils";

// Mirrors ai-status-badge / severity-badge shape (mono uppercase pill).
const MAP: Record<FixReviewState, { label: string; className: string }> = {
  proposed: { label: "Proposed", className: "bg-status-progress/15 text-status-progress" },
  approved: { label: "Approved", className: "bg-status-progress/15 text-status-progress" },
  applying: { label: "Applying", className: "bg-status-progress/15 text-status-progress" },
  validated: { label: "Validated", className: "bg-emerald-500/15 text-emerald-500" },
  pr_open: { label: "PR opened", className: "bg-emerald-500/15 text-emerald-500" },
  manual_review: { label: "Manual review", className: "bg-severity-medium/15 text-severity-medium" },
  dismissed: { label: "Dismissed", className: "bg-muted text-muted-foreground" },
  failed: { label: "Failed", className: "bg-severity-critical/15 text-severity-critical" },
};

export function FixReviewStateBadge({ state, className }: { state: FixReviewState; className?: string }) {
  const { label, className: tone } = MAP[state];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide",
        tone,
        className
      )}
    >
      {label}
    </span>
  );
}

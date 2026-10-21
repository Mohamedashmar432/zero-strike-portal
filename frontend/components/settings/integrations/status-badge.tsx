import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";
import type { StatusTone } from "./integration-status";

// Same left-rule badge as ScanStatusBadge, on the same status tokens, so "connected" reads like
// "completed" and "needs reconnect" like "failed" instead of inventing a second status language.
const badge = cva(
  "inline-flex items-center gap-1.5 rounded-sm border-l-2 px-1.5 py-0.5 font-mono text-[11px] font-semibold leading-none tracking-[0.08em] whitespace-nowrap uppercase",
  {
    variants: {
      tone: {
        ok: "border-status-success bg-status-success-tint text-status-success",
        warn: "border-severity-medium bg-severity-medium-tint text-severity-medium",
        bad: "border-severity-critical bg-severity-critical-tint text-severity-critical",
        muted: "border-border bg-muted text-muted-foreground",
        pending: "border-status-progress bg-status-progress-tint text-status-progress",
      },
    },
    defaultVariants: { tone: "muted" },
  }
);

export function IntegrationStatusBadge({
  tone,
  label,
  hint,
  className,
}: {
  tone: StatusTone;
  label: string;
  hint?: string;
  className?: string;
}) {
  return (
    <span className={cn(badge({ tone }), className)} title={hint}>
      {tone === "pending" && <span className="pulse-signal size-1.5 rounded-full bg-current" />}
      {label}
    </span>
  );
}

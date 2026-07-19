import type { AiAnalysisStatus } from "@/lib/api/ai";
import { cn } from "@/lib/utils";

// Only the states worth surfacing as a tag next to a scan. "completed"/"not_requested" show
// nothing (the AI result panel / trigger button covers those). Mirrors scan-status-badge's
// CVA + pulsing-dot shape, using the status-progress token for the active state.
const CLASS: Record<"queued" | "in_progress" | "failed", string> = {
  queued: "bg-severity-medium/15 text-severity-medium",
  in_progress: "bg-status-progress/15 text-status-progress",
  failed: "bg-severity-critical/15 text-severity-critical",
};

const LABEL: Record<"queued" | "in_progress" | "failed", string> = {
  queued: "AI QUEUED",
  in_progress: "AI ANALYZING",
  failed: "AI FAILED",
};

function formatEta(ms: number): string {
  const secs = Math.max(1, Math.round(ms / 1000));
  if (secs < 60) return `~${secs}s left`;
  return `~${Math.round(secs / 60)}m left`;
}

// Progress detail for the analyzing tag: "40% · ~24s left". ETA is derived from how long the
// completed batches have taken so far, extrapolated to the remaining ones — naturally accounts
// for concurrency (elapsed already reflects it). Recomputed on each poll; no ticking timer.
function progressText(
  startedAt: string | null | undefined,
  completed: number,
  total: number
): string | null {
  if (!total) return null;
  const pct = Math.round((completed / total) * 100);
  let eta: string | null = null;
  if (startedAt && completed > 0 && completed < total) {
    const elapsedMs = Date.now() - new Date(startedAt).getTime();
    if (elapsedMs > 0) eta = formatEta((elapsedMs / completed) * (total - completed));
  }
  return eta ? `${pct}% · ${eta}` : `${pct}%`;
}

export function AiStatusBadge({
  status,
  startedAt,
  progressCompleted = 0,
  progressTotal = 0,
  className,
}: {
  status: AiAnalysisStatus | null | undefined;
  startedAt?: string | null;
  progressCompleted?: number;
  progressTotal?: number;
  className?: string;
}) {
  if (status !== "queued" && status !== "in_progress" && status !== "failed") return null;
  const progress = status === "in_progress" ? progressText(startedAt, progressCompleted, progressTotal) : null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 font-mono text-xs font-medium uppercase tracking-wide",
        CLASS[status],
        className
      )}
    >
      {status === "in_progress" && <span className="size-1.5 animate-pulse rounded-sm bg-current" />}
      {LABEL[status]}
      {progress && <span className="normal-case opacity-80">· {progress}</span>}
    </span>
  );
}

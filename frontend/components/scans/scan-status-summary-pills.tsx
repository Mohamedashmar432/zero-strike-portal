import { cn } from "@/lib/utils";
import type { ScanStatusCounts } from "@/lib/api/projects";
import type { ScanStatus } from "@/lib/api/scans";

const STATUS_ORDER: ScanStatus[] = ["running", "queued", "pending", "failed", "completed"];

const STATUS_PILL_CLASS: Record<ScanStatus, string> = {
  pending: "bg-severity-info/15 text-severity-info",
  queued: "bg-severity-medium/15 text-severity-medium",
  running: "bg-status-progress/15 text-status-progress",
  completed: "bg-status-success/15 text-status-success",
  failed: "bg-severity-critical/15 text-severity-critical",
};

// Only shows non-zero, non-"completed" buckets by default — a pile of completed scans
// isn't interesting on a list page; in-flight/failed scans are what need attention.
export function ScanStatusSummaryPills({ counts }: { counts: ScanStatusCounts }) {
  const nonZero = STATUS_ORDER.filter((status) => counts[status] > 0);
  if (nonZero.length === 0) {
    return <span className="text-xs text-muted-foreground">{counts.completed > 0 ? `${counts.completed} completed` : "No scans"}</span>;
  }
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {nonZero.map((status) => (
        <span
          key={status}
          title={status}
          className={cn(
            "inline-flex items-center gap-1 rounded-sm px-2 py-0.5 font-mono text-xs font-semibold uppercase",
            STATUS_PILL_CLASS[status]
          )}
        >
          {counts[status]} {status}
        </span>
      ))}
    </div>
  );
}

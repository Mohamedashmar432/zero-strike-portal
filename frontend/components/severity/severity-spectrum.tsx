import type { SeverityCounts } from "@/lib/api/dashboard";
import type { Severity } from "@/lib/api/findings";
import { cn } from "@/lib/utils";
import { SEVERITY_ORDER } from "./severity-count-pills";

const SEVERITY_BG: Record<Severity, string> = {
  critical: "bg-severity-critical",
  high: "bg-severity-high",
  medium: "bg-severity-medium",
  low: "bg-severity-low",
  info: "bg-severity-info",
};

/**
 * The severity spectrum: a proportional stacked bar of one scan/project/repo's
 * findings, always in critical -> info order.
 *
 * This is the app's signature read. A row of numbers makes you do arithmetic to
 * answer "is this bad?"; a spectrum answers it in peripheral vision — you learn
 * the shape of a healthy repo (thin, cool, right-weighted) versus a compromised
 * one (fat red on the left) and can then scan a 40-row table without reading a
 * single digit.
 *
 * Two deliberate distortions, both in service of not lying by omission:
 *  - Every non-zero tier gets a floor width, so a single CRITICAL among 4,000
 *    infos is still visible. Proportion is preserved above the floor.
 *  - Zero findings render as a flat muted rule, not an empty box, so "clean"
 *    and "not scanned" don't look the same.
 */
export function SeveritySpectrum({
  counts,
  className,
  height = "h-1.5",
  scanStatus,
}: {
  counts: SeverityCounts;
  className?: string;
  /** Tailwind height class. `h-1.5` inline in rows, `h-2.5` for hero panels. */
  height?: string;
  /**
   * The owning scan's status, when this spectrum represents a single scan.
   *
   * Without it, a scan that FAILED (or is still queued/pending) reports zero
   * findings and therefore renders identically to a genuinely clean repo — a
   * false all-clear, which is the worst failure mode a security tool has. Pass
   * it and a non-completed scan renders as indeterminate instead.
   */
  scanStatus?: string;
}) {
  const present = SEVERITY_ORDER.filter((s) => counts[s] > 0);
  const total = present.reduce((sum, s) => sum + counts[s], 0);
  // A running scan with partial results still shows them; only an *empty*
  // non-completed scan is unknown.
  const noResult = total === 0 && !!scanStatus && scanStatus !== "completed";

  const label = total === 0
    ? (noResult ? `No result — scan ${scanStatus}` : "No findings")
    : present.map((s) => `${counts[s]} ${s}`).join(", ");

  if (total === 0) {
    return (
      <div
        className={cn(
          "w-full rounded-sm",
          // Hatched, not filled: reads as "no signal on this channel" rather
          // than as a measured zero.
          noResult
            ? "bg-[repeating-linear-gradient(135deg,var(--hairline)_0_3px,transparent_3px_6px)] ring-1 ring-inset ring-hairline"
            : "bg-muted",
          height,
          className
        )}
        role="img"
        aria-label={label}
        title={label}
      />
    );
  }

  // Floor each visible tier at 4% so a lone critical never rounds away, then
  // distribute what's left proportionally.
  const FLOOR = 4;
  const slack = Math.max(0, 100 - FLOOR * present.length);

  return (
    <div
      className={cn("flex w-full gap-px overflow-hidden rounded-sm", height, className)}
      role="img"
      aria-label={label}
      title={label}
    >
      {present.map((severity) => (
        <div
          key={severity}
          className={cn("h-full first:rounded-l-sm last:rounded-r-sm", SEVERITY_BG[severity])}
          style={{ width: `${FLOOR + (counts[severity] / total) * slack}%` }}
        />
      ))}
    </div>
  );
}

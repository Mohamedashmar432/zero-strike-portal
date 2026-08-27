import { cn } from "@/lib/utils";
import type { SeverityCounts } from "@/lib/api/dashboard";
import type { Severity } from "@/lib/api/findings";

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

export const SEVERITY_LETTER: Record<Severity, string> = {
  critical: "C",
  high: "H",
  medium: "M",
  low: "L",
  info: "I",
};

export const SEVERITY_PILL_CLASS: Record<Severity, string> = {
  critical: "bg-severity-critical-tint text-severity-critical",
  high: "bg-severity-high-tint text-severity-high",
  medium: "bg-severity-medium-tint text-severity-medium",
  low: "bg-severity-low-tint text-severity-low",
  info: "bg-severity-info-tint text-severity-info",
};

/**
 * Severity counts as one joined segmented readout — a single bordered strip
 * divided by hairlines, not five floating pills.
 *
 * The joined form matters at table density: five separate rounded chips with
 * gaps between them read as five unrelated objects and every row becomes visual
 * confetti. Joined, the whole group reads as one value with parts, and its
 * overall width is itself a signal.
 */
export function SeverityCountPills({
  counts,
  showLabel = true,
  scanStatus,
}: {
  counts: SeverityCounts;
  showLabel?: boolean;
  /**
   * The owning scan's status, when these counts come from a single scan.
   * A FAILED/queued/pending scan reports zero findings, which without this
   * would render the same confident green "Clean" as a genuinely clean repo.
   * See the same guard in SeveritySpectrum.
   */
  scanStatus?: string;
}) {
  const nonZero = SEVERITY_ORDER.filter((severity) => counts[severity] > 0);

  if (nonZero.length === 0) {
    if (scanStatus && scanStatus !== "completed") {
      return (
        <span
          className="legend inline-flex items-center gap-1.5 text-muted-foreground"
          title={`No result — scan ${scanStatus}`}
        >
          <span className="size-1.5 rounded-full ring-1 ring-muted-foreground/60" />
          No result
        </span>
      );
    }
    return (
      <span className="legend inline-flex items-center gap-1.5 text-muted-foreground">
        <span className="size-1.5 rounded-full bg-status-success" />
        Clean
      </span>
    );
  }

  return (
    <div className="inline-flex overflow-hidden rounded-sm border border-hairline">
      {nonZero.map((severity, i) => (
        <span
          key={severity}
          title={`${counts[severity]} ${severity}`}
          className={cn(
            "inline-flex min-w-8 items-center justify-center gap-0.5 px-1.5 py-0.5 font-mono text-[11px] font-semibold leading-none tabular-nums",
            i > 0 && "hairline-x",
            SEVERITY_PILL_CLASS[severity]
          )}
        >
          {counts[severity]}
          {showLabel && (
            <span className="text-[9px] font-bold opacity-60">{SEVERITY_LETTER[severity]}</span>
          )}
        </span>
      ))}
    </div>
  );
}

// Not a real risk-scoring model — just buckets a project/repo's latest severity
// counts into three status tiers.
//
// The returned className carries its own `border-l-2` + mono/uppercase so the
// four existing call sites keep working unchanged and all pick up the marker
// treatment from one place.
const RISK_TAG = "border-l-2 font-mono text-[10px] font-semibold uppercase tracking-[0.09em]";

export function projectRiskStatus(counts: SeverityCounts, scanStatus?: string) {
  // "Stable" is an assertion about the code, so it must never be derived from a
  // scan that did not finish. A failed scan reports zero findings, which would
  // otherwise print a confident green STABLE over a project with real criticals.
  const total =
    counts.critical + counts.high + counts.medium + counts.low + counts.info;
  if (total === 0 && scanStatus && scanStatus !== "completed") {
    return {
      label: "Unknown",
      className: cn(RISK_TAG, "border-severity-info bg-severity-info-tint text-severity-info"),
    };
  }
  if (counts.critical > 0)
    return {
      label: "At Risk",
      className: cn(RISK_TAG, "border-severity-critical bg-severity-critical-tint text-severity-critical"),
    };
  if (counts.high > 0)
    return {
      label: "Action Needed",
      className: cn(RISK_TAG, "border-severity-high bg-severity-high-tint text-severity-high"),
    };
  return {
    label: "Stable",
    className: cn(RISK_TAG, "border-status-success bg-status-success-tint text-status-success"),
  };
}

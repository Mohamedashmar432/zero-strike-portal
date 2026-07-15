// Mirrors lib/owasp.ts — priority tier metadata for the filter dropdown and the
// per-finding priority badge. Independent of severity: see backend/app/core/priority.py.
export type PriorityTier = "critical" | "high" | "medium" | "low";

export const PRIORITY_TIERS: PriorityTier[] = ["critical", "high", "medium", "low"];

export const PRIORITY_LABELS: Record<PriorityTier, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const PRIORITY_CLASS: Record<PriorityTier, string> = {
  critical: "text-severity-critical",
  high: "text-severity-high",
  medium: "text-severity-medium",
  low: "text-severity-low",
};

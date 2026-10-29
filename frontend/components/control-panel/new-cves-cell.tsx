import type { NewCves } from "@/lib/api/project-insights";

const SEV: Record<string, string> = { critical: "C", high: "H", medium: "M", low: "L", info: "I" };
const sev = (s: string) => SEV[s.toLowerCase()] ?? s;

/** `3 · CVE-2026-1234 (H), GHSA-xxxx (C)` — the newest two ids, the full list on hover. */
export function NewCvesCell({ cves }: { cves: NewCves }) {
  if (cves.count === 0) return <span className="text-muted-foreground">—</span>;
  const more = cves.count - cves.latest.length;
  const full = cves.latest.map((c) => `${c.id} (${sev(c.severity)})`).join(", ");
  return (
    <span
      className="font-mono"
      title={`${cves.count} new advisory id${cves.count === 1 ? "" : "s"}: ${full}${more > 0 ? ` and ${more} more` : ""}`}
    >
      <span className="tabular-nums text-foreground">{cves.count}</span>
      {full && <span className="text-muted-foreground"> · {full}</span>}
      {more > 0 && <span className="text-muted-foreground"> +{more}</span>}
    </span>
  );
}

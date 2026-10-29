"use client";

import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DigestPreview } from "@/lib/api/digest";
import { fmt, when } from "./date-range";
import { NewCvesCell } from "./new-cves-cell";

const num = "text-right font-mono tabular-nums";

function Fact({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div>
      <dt className="legend inline text-muted-foreground">{label} </dt>
      <dd className={bad ? "inline font-mono text-severity-critical" : "inline font-mono"}>{value}</dd>
    </div>
  );
}

/** The same table the Teams card carries, so an admin sees what will be posted before it is. */
export function DigestPreviewTable({
  preview,
  isLoading,
  isError,
  onRefresh,
}: {
  preview: DigestPreview | undefined;
  isLoading: boolean;
  isError: boolean;
  onRefresh: () => void;
}) {
  if (isError) return <p className="text-sm text-destructive">Failed to build the digest preview.</p>;
  if (!preview) return <p className="text-sm text-muted-foreground">{isLoading ? "Building preview…" : ""}</p>;

  const { totals, scanner: s } = preview;
  const totalCves = preview.rows.reduce((n, r) => n + r.new_cves.count, 0);

  return (
    <div className="space-y-4 rounded-lg border border-border p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          Preview for {when(preview.period_start)} to {when(preview.period_end)}
        </p>
        <Button variant="ghost" size="sm" disabled={isLoading} onClick={onRefresh}>
          <RefreshCw /> Refresh
        </Button>
      </div>

      <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/40 text-xs">
              <TableHead className="py-2.5">Project</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Pipeline runs</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Pipeline failed</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Cloud scans</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Cloud failed</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Critical</TableHead>
              <TableHead className={`py-2.5 ${num}`}>High</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Quota</TableHead>
              <TableHead className="py-2.5">New CVEs</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {preview.rows.map((r) => (
              <TableRow key={r.project_id} className="text-xs">
                <TableCell className="font-medium text-foreground">{r.name}</TableCell>
                <TableCell className={num}>{fmt(r.pipeline_runs)}</TableCell>
                <TableCell className={`${num} ${r.pipeline_failed > 0 ? "text-severity-critical" : ""}`}>
                  {fmt(r.pipeline_failed)}
                </TableCell>
                <TableCell className={num}>{fmt(r.cloud_scans)}</TableCell>
                <TableCell className={`${num} ${r.cloud_failed > 0 ? "text-severity-critical" : ""}`}>
                  {fmt(r.cloud_failed)}
                </TableCell>
                <TableCell className={`${num} ${r.critical > 0 ? "text-severity-critical" : ""}`}>
                  {fmt(r.critical)}
                </TableCell>
                <TableCell className={`${num} ${r.high > 0 ? "text-severity-high" : ""}`}>{fmt(r.high)}</TableCell>
                <TableCell className={num}>
                  {r.quota_used}/{r.quota_limit}
                </TableCell>
                <TableCell className="max-w-64 truncate">
                  <NewCvesCell cves={r.new_cves} />
                </TableCell>
              </TableRow>
            ))}
            <TableRow className="border-t-2 bg-muted/30 text-xs font-medium hover:bg-muted/30">
              <TableCell>Total</TableCell>
              <TableCell className={num}>{fmt(totals.pipeline_runs)}</TableCell>
              <TableCell className={num}>{fmt(totals.pipeline_failed)}</TableCell>
              <TableCell className={num}>{fmt(totals.cloud_scans)}</TableCell>
              <TableCell className={num}>{fmt(totals.cloud_failed)}</TableCell>
              <TableCell className={num}>{fmt(totals.critical)}</TableCell>
              <TableCell className={num}>{fmt(totals.high)}</TableCell>
              <TableCell className={num}>
                {totals.quota_used}/{totals.quota_limit}
              </TableCell>
              <TableCell className="font-mono tabular-nums">{fmt(totals.new_cves?.count ?? totalCves)}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      <div className="space-y-1.5">
        <h3 className="legend text-foreground">Scanner health</h3>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
          <Fact label="Engine" value={s.engine_available ? "available" : "unavailable"} bad={!s.engine_available} />
          <Fact label="Backend scanner" value={s.backend_scanner_version ?? "unknown"} />
          <Fact label="Latest published" value={s.latest_binary_version ?? "none"} />
          <Fact
            label="CI runners on older scanner"
            value={String(s.outdated_ci_runners)}
            bad={s.outdated_ci_runners > 0}
          />
          <Fact
            label="Rule pack"
            value={`${s.rule_pack_version ?? "unknown"}${s.rule_count !== null ? ` (${fmt(s.rule_count)} rules)` : ""}`}
          />
          <Fact label="OSV.dev" value={s.osv_reachable ? "reachable" : "unreachable"} bad={!s.osv_reachable} />
        </dl>
        {s.new_cve_ids.length > 0 && (
          <p className="font-mono text-xs text-muted-foreground">New advisory ids: {s.new_cve_ids.join(", ")}</p>
        )}
      </div>

      {preview.stale_projects.length > 0 && (
        <div className="space-y-1">
          <h3 className="legend text-foreground">Stale projects</h3>
          <ul className="space-y-0.5 text-xs text-muted-foreground">
            {preview.stale_projects.map((p) => (
              <li key={p.project_id}>
                <span className="text-foreground">{p.name}</span> — last scan {when(p.last_scan_at)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {preview.quota_warnings.length > 0 && (
        <div className="space-y-1">
          <h3 className="legend text-foreground">Quota warnings</h3>
          <ul className="space-y-0.5 text-xs text-muted-foreground">
            {preview.quota_warnings.map((p) => (
              <li key={p.project_id}>
                <span className="text-foreground">{p.name}</span> — {p.used}/{p.limit} cloud scans used
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

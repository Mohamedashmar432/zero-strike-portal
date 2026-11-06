"use client";

import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { DigestPreview, DigestRow } from "@/lib/api/digest";
import { fmt, when } from "./date-range";

const num = "text-right font-mono tabular-nums";

function Fact({ label, value, bad }: { label: string; value: string; bad?: boolean }) {
  return (
    <div>
      <dt className="legend inline text-muted-foreground">{label} </dt>
      <dd className={bad ? "inline font-mono text-severity-critical" : "inline font-mono"}>{value}</dd>
    </div>
  );
}

const failRate = (r: DigestRow) => {
  const total = r.pipeline_runs + r.cloud_scans;
  return total > 0 ? `${Math.round(((r.pipeline_failed + r.cloud_failed) / total) * 100)}%` : "-";
};

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
  const totalFailed = totals.pipeline_failed + totals.cloud_failed;

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
              <TableHead className={`py-2.5 ${num}`}>CI/CD</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Cloud</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Critical</TableHead>
              <TableHead className={`py-2.5 ${num}`}>High</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Fail rate</TableHead>
              <TableHead className={`py-2.5 ${num}`}>Resolved</TableHead>
              <TableHead className={`py-2.5 ${num}`}>New findings</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {preview.rows.map((r) => (
              <TableRow key={r.project_id} className="text-xs">
                <TableCell className="font-medium text-foreground">{r.name}</TableCell>
                <TableCell className={num}>{fmt(r.pipeline_runs)}</TableCell>
                <TableCell className={num}>{fmt(r.cloud_scans)}</TableCell>
                <TableCell className={`${num} ${r.critical > 0 ? "text-severity-critical" : ""}`}>
                  {fmt(r.critical)}
                </TableCell>
                <TableCell className={`${num} ${r.high > 0 ? "text-severity-high" : ""}`}>{fmt(r.high)}</TableCell>
                <TableCell
                  className={`${num} ${r.pipeline_failed + r.cloud_failed > 0 ? "text-severity-critical" : ""}`}
                >
                  {failRate(r)}
                </TableCell>
                <TableCell className={num}>{fmt(r.resolved)}</TableCell>
                <TableCell className={num}>{fmt(r.new_findings)}</TableCell>
              </TableRow>
            ))}
            <TableRow className="border-t-2 bg-muted/30 text-xs font-medium hover:bg-muted/30">
              <TableCell>Total</TableCell>
              <TableCell className={num}>{fmt(totals.pipeline_runs)}</TableCell>
              <TableCell className={num}>{fmt(totals.cloud_scans)}</TableCell>
              <TableCell className={num}>{fmt(totals.critical)}</TableCell>
              <TableCell className={num}>{fmt(totals.high)}</TableCell>
              <TableCell className={num}>{totalFailed} failed</TableCell>
              <TableCell className={num}>{fmt(preview.rows.reduce((n, r) => n + r.resolved, 0))}</TableCell>
              <TableCell className={num}>{fmt(preview.rows.reduce((n, r) => n + r.new_findings, 0))}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>

      <div className="space-y-1.5">
        <h3 className="legend text-foreground">Scanner</h3>
        <dl className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
          <Fact label="Engine" value={s.engine_available ? "available" : "unavailable"} bad={!s.engine_available} />
          <Fact label="Backend scanner" value={s.backend_scanner_version ?? "unknown"} />
          <Fact label="Latest published" value={s.latest_binary_version ?? "none"} />
          <Fact
            label="Projects on an older scanner"
            value={String(s.projects_outdated)}
            bad={s.projects_outdated > 0}
          />
          <Fact label="New CVEs added" value={fmt(s.new_advisory_count)} />
        </dl>
        <h3 className="legend pt-1 text-foreground">Pipelines on an older scanner</h3>
        {!s.latest_binary_version ? (
          <p className="text-xs text-muted-foreground">
            No scanner binary is published, so pipeline versions cannot be compared.
          </p>
        ) : s.outdated_pipelines.length === 0 ? (
          <p className="text-xs text-muted-foreground">Every pipeline in this period used {s.latest_binary_version}.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40 text-xs">
                <TableHead className="py-2.5">Project</TableHead>
                <TableHead className="py-2.5">Repository</TableHead>
                <TableHead className="py-2.5">Scanner used</TableHead>
                <TableHead className={`py-2.5 ${num}`}>Runs</TableHead>
                <TableHead className="py-2.5">Last run</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {s.outdated_pipelines.map((o) => (
                <TableRow key={`${o.project_id}|${o.repository}|${o.scanner_version}`} className="text-xs">
                  <TableCell className="font-medium text-foreground">{o.project}</TableCell>
                  <TableCell className="font-mono">{o.repository}</TableCell>
                  <TableCell className="font-mono">{o.scanner_version}</TableCell>
                  <TableCell className={num}>{fmt(o.runs)}</TableCell>
                  <TableCell>{when(o.last_run_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
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

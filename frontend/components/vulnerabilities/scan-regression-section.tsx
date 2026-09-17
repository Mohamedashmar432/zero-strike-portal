"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { RegressionBadge } from "@/components/vulnerabilities/regression-badge";
import { getScanRegression, type RegressionState } from "@/lib/api/vulnerabilities";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

/**
 * What this scan actually changed: New / Reopened / Fixed / Unchanged.
 *
 * Its own section rather than a filter on the findings table, because "what moved since last
 * time" is a first-class scan outcome — a reopened critical is the single most important thing
 * on this page and must not be something you have to go looking for.
 *
 * The counts come from bookkeeping stamped once at reconciliation time, not from a diff computed
 * here. Each bucket's `count` is the true total; the API returns only a capped preview of the
 * rows themselves, so every tile links into the work queue rather than pretending to list them.
 */

const ORDER: RegressionState[] = ["new", "reopened", "fixed", "unchanged"];

const TONE: Record<RegressionState, string> = {
  new: "text-severity-high",
  reopened: "text-severity-critical",
  fixed: "text-status-success",
  unchanged: "text-muted-foreground",
};

export function ScanRegressionSection({ projectId, scanId }: { projectId: string; scanId: string }) {
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.scans.regression(scanId),
    queryFn: () => getScanRegression(projectId, scanId),
  });

  if (isError) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">
          Change Since Last Scan
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : data && !data.is_latest_for_scope ? (
          // A superseded scan's counts have drained to whichever later scan re-observed each
          // vulnerability, so they would read as "this scan changed nothing" when it may have
          // introduced everything. Say the numbers are gone rather than show misleading zeros.
          <p className="text-xs text-muted-foreground">
            A newer scan has since run for this repository. What changed is tracked against the
            most recent scan, so the breakdown is no longer available for this one.
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {data?.has_baseline ? (
                <>Compared with the previous completed scan of this repository.</>
              ) : (
                // Saying "0 fixed" against no baseline would read as "nothing was fixed"
                // rather than "there is nothing to compare against".
                <>First comparable scan; no baseline exists.</>
              )}
            </p>

            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              {ORDER.map((state) => {
                const bucket = data?.[state];
                return (
                  <Link
                    key={state}
                    href={`/projects/${projectId}/vulnerabilities?regression=${state}`}
                    className="group rounded-lg border border-border bg-card p-3 transition-colors hover:border-foreground/30"
                  >
                    <RegressionBadge state={state} />
                    <p
                      className={cn(
                        "readout mt-2 text-xl leading-none tabular-nums",
                        TONE[state]
                      )}
                    >
                      {bucket?.count ?? 0}
                    </p>
                  </Link>
                );
              })}
            </div>

            {data?.fixed.items.length ? (
              <div className="pt-1">
                <p className="legend mb-1.5 text-muted-foreground">Resolved by this scan</p>
                <ul className="space-y-1">
                  {data.fixed.items.slice(0, 5).map((v) => (
                    <li key={v.id} className="truncate text-xs">
                      <Link
                        href={`/projects/${projectId}/vulnerabilities/${v.id}`}
                        className="underline-offset-4 hover:underline hover:text-primary"
                      >
                        {v.current_rule_name ?? v.current_rule_id ?? v.fingerprint.slice(0, 12)}
                      </Link>
                      {v.current_location ? (
                        <span className="ml-1.5 font-mono text-muted-foreground">
                          {v.current_location.file}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>
                {data.fixed.count > data.fixed.items.length && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    and {data.fixed.count - data.fixed.items.length} more.
                  </p>
                )}
              </div>
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}

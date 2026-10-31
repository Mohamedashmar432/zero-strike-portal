"use client";

import { useQuery } from "@tanstack/react-query";
import { DeliveryChips } from "@/components/alerts/delivery-chips";
import { RelativeTime } from "@/components/common/relative-time";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getProjectLiveAlerts } from "@/lib/api/live-alerts";
import { queryKeys } from "@/lib/api/query-keys";
import { effectivePolicyText } from "@/lib/live-alerts";
import { parseApiDate } from "@/lib/utils";

const day = (iso: string) => parseApiDate(iso).toLocaleDateString();

/** Member-visible: what this project is alerted on, the inventories it is matched against, and the
 * last 90 days of live dependency alerts. Direct/transitive is deliberately never shown. */
export function LiveAlertsCard({ projectId }: { projectId: string }) {
  const q = useQuery({
    queryKey: queryKeys.projects.liveAlerts(projectId),
    queryFn: () => getProjectLiveAlerts(projectId),
  });
  const d = q.data;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm font-normal text-muted-foreground">Live dependency alerts</CardTitle>
        {d && <p className="text-sm">{effectivePolicyText(d)}</p>}
      </CardHeader>
      <CardContent className="space-y-4">
        {q.isLoading && <Skeleton className="h-20 w-full" />}
        {q.isError && <p className="text-sm text-destructive">Failed to load live dependency alerts.</p>}
        {d && (
          <>
            {d.inventories.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No dependency inventory yet. It is created by the next scan once the scanner is on the new version.
              </p>
            ) : (
              <ul className="space-y-1 text-sm">
                {d.inventories.map((i) => (
                  <li key={`${i.repo_label}-${i.scan_type}`}>
                    <span className="font-mono text-xs">{i.repo_label}</span>: {i.dep_count.toLocaleString()}{" "}
                    dependencies, scan {day(i.scanned_at)}, scanner {i.scanner_version ?? "unknown"}
                    {i.truncated && (
                      <span className="text-muted-foreground"> (list truncated; some dependencies are not matched)</span>
                    )}
                  </li>
                ))}
              </ul>
            )}

            <div className="space-y-2">
              <p className="text-xs text-muted-foreground">Alerts in the last 90 days</p>
              {d.alerts.length === 0 ? (
                <p className="text-sm text-muted-foreground">No live alerts for this project.</p>
              ) : (
                <ul className="divide-y divide-border rounded-lg border border-border">
                  {d.alerts.map((a) => {
                    const manifests = [...new Set(a.locations.flatMap((l) => l.manifests))];
                    return (
                      <li key={a.id} className="space-y-1.5 p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <SeverityBadge severity={a.severity} />
                          <span className="font-mono text-xs">{a.advisory_id}</span>
                          <span className="font-mono text-xs text-muted-foreground">
                            {a.package}@{a.version}
                          </span>
                        </div>
                        {a.summary && <p className="text-xs text-muted-foreground">{a.summary}</p>}
                        <p className="text-xs text-muted-foreground">
                          Released <RelativeTime iso={a.published_at} /> ({day(a.published_at)}). Fixed in:{" "}
                          {a.fixed_versions.length ? a.fixed_versions.join(", ") : "no fix yet"}.
                          {manifests.length > 0 && <> Affected manifests: {manifests.join(", ")}.</>}
                        </p>
                        <DeliveryChips delivery={a.delivery} />
                      </li>
                    );
                  })}
                </ul>
              )}
              {!d.email_delivery_configured && (
                <p className="text-xs text-muted-foreground">
                  Email is not configured on this portal; email copies are not sent.
                </p>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

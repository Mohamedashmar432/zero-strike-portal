"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Inbox, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { MetricStrip } from "@/components/common/metric-strip";
import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  type AutoFixQuotaRequest,
  type AutoFixQuotaRequestStatus,
  decideQuotaRequest,
  listAllQuotaRequests,
} from "@/lib/api/auto-fix-quota";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import { cn } from "@/lib/utils";

const STATUS_TAG: Record<AutoFixQuotaRequestStatus, string> = {
  pending: "border-severity-medium bg-severity-medium-tint text-severity-medium",
  approved: "border-status-success bg-status-success-tint text-status-success",
  rejected: "border-severity-critical bg-severity-critical-tint text-severity-critical",
};

type Filter = "pending" | "approved" | "rejected" | "all";

export default function AutoFixRequestsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<Filter>("pending");
  const [search, setSearch] = useState("");
  const [target, setTarget] = useState<AutoFixQuotaRequest | null>(null);
  const [grant, setGrant] = useState("");
  const [note, setNote] = useState("");

  const statusParam = filter === "all" ? undefined : filter;
  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.autoFixQuotaRequests(statusParam),
    queryFn: () => listAllQuotaRequests(statusParam),
  });

  const decide = useMutation({
    mutationFn: ({ id, approve }: { id: string; approve: boolean }) =>
      decideQuotaRequest(id, {
        approve,
        ...(approve && grant.trim() ? { granted_additional: Number(grant) } : {}),
        ...(note.trim() ? { decision_note: note.trim() } : {}),
      }),
    onSuccess: (req) => {
      toast.success(
        req.status === "approved"
          ? `Granted +${req.granted_additional} findings.`
          : "Request rejected."
      );
      setTarget(null);
      setGrant("");
      setNote("");
      // Every filtered view plus the nav badge share this prefix.
      qc.invalidateQueries({ queryKey: ["admin", "auto-fix-quota-requests"] });
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Could not record the decision."),
  });

  const items = (data?.items ?? []).filter((r) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      (r.project_name ?? "").toLowerCase().includes(q) ||
      (r.requested_by_email ?? "").toLowerCase().includes(q) ||
      r.reason.toLowerCase().includes(q)
    );
  });

  const approvedTotal = (data?.items ?? [])
    .filter((r) => r.status === "approved")
    .reduce((sum, r) => sum + (r.granted_additional ?? 0), 0);

  const grantNum = Number(grant);
  const grantValid =
    grant.trim() === "" || (Number.isInteger(grantNum) && grantNum >= 1 && grantNum <= 500);

  return (
    <div className="space-y-7">
      <div className="signal-in">
        <PageHeader
          eyebrow="Administration / Requests"
          title="Project Requests"
          description="Requests raised from a project that need an admin decision. Today these are all AI Auto-Fix headroom asks on one scan — approving one authorises additional LLM spend, so each request carries a stated purpose."
        />
      </div>

      <div className="signal-in" style={{ "--d": "60ms" } as React.CSSProperties}>
        <MetricStrip
          isLoading={isLoading}
          metrics={[
            {
              label: "Awaiting review",
              value: (data?.pending_count ?? 0).toLocaleString(),
              hint: "Across every project",
              tone: (data?.pending_count ?? 0) > 0 ? ("medium" as const) : ("default" as const),
            },
            {
              label: "In this view",
              value: items.length.toLocaleString(),
              hint: filter === "all" ? "All statuses" : `Status: ${filter}`,
            },
            {
              label: "Granted here",
              value: approvedTotal.toLocaleString(),
              hint: "Extra findings approved in the listed requests",
              tone: "signal" as const,
            },
          ]}
        />
      </div>

      <div className="signal-in space-y-3" style={{ "--d": "120ms" } as React.CSSProperties}>
        <FilterBar
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="Project, requester or purpose…"
          facets={[
            {
              type: "select",
              value: filter,
              onChange: (v) => setFilter(v as Filter),
              placeholder: "Status",
              options: [
                { value: "pending", label: "Pending" },
                { value: "approved", label: "Approved" },
                { value: "rejected", label: "Rejected" },
                { value: "all", label: "All statuses" },
              ],
            },
          ]}
        />

        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load project requests."
          isEmpty={items.length === 0}
          emptyState={
            <EmptyState
              icon={Inbox}
              title={filter === "pending" ? "Nothing awaiting review" : "No requests match"}
              description={
                filter === "pending"
                  ? "Requests appear here when a team runs out of auto-fix allowance on a scan."
                  : "Try a different status or clear the search."
              }
            />
          }
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Project</TableHead>
                <TableHead>Requested by</TableHead>
                <TableHead>Asked</TableHead>
                <TableHead>Purpose</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Raised</TableHead>
                <TableHead className="w-40">
                  <span className="sr-only">Decision</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((r) => (
                <TableRow key={r.id}>
                  <TableCell>
                    <Link
                      href={`/projects/${r.project_id}/auto-fix/${r.scan_id}`}
                      className="font-mono text-[13px] font-semibold text-foreground underline-offset-4 transition-colors hover:text-signal hover:underline"
                    >
                      {r.project_name ?? r.project_id}
                    </Link>
                    <span className="block font-mono text-[10px] text-muted-foreground">
                      scan {r.scan_id.slice(0, 8)}
                    </span>
                  </TableCell>
                  <TableCell className="font-mono text-[11px] text-muted-foreground">
                    {r.requested_by_email ?? r.requested_by}
                  </TableCell>
                  <TableCell className="readout text-sm text-foreground">
                    +{r.requested_additional}
                  </TableCell>
                  <TableCell className="max-w-[26rem] whitespace-normal text-[13px] leading-relaxed text-muted-foreground">
                    {r.reason}
                  </TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        "legend rounded-sm border-l-2 px-1.5 py-0.5",
                        STATUS_TAG[r.status]
                      )}
                    >
                      {r.status}
                    </span>
                    {r.status === "approved" && r.granted_additional != null && (
                      <span className="block font-mono text-[10px] text-muted-foreground">
                        granted +{r.granted_additional}
                      </span>
                    )}
                    {r.decision_note && (
                      <span className="mt-0.5 block max-w-56 whitespace-normal text-[11px] leading-snug text-muted-foreground">
                        “{r.decision_note}”
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-[11px] text-muted-foreground">
                    {new Date(r.created_at).toLocaleString()}
                  </TableCell>
                  <TableCell>
                    {r.status === "pending" ? (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setTarget(r);
                          setGrant(String(r.requested_additional));
                          setNote("");
                        }}
                      >
                        Review
                      </Button>
                    ) : (
                      <span className="font-mono text-[11px] text-muted-foreground">
                        {r.decided_by_email ?? "—"}
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>

      <Dialog open={target !== null} onOpenChange={(o) => !o && setTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Review project request</DialogTitle>
            <DialogDescription>
              {target?.requested_by_email ?? "A member"} asked for{" "}
              <span className="font-mono text-foreground">+{target?.requested_additional}</span>{" "}
              additional auto-fixable findings on one scan of{" "}
              <span className="font-mono text-foreground">
                {target?.project_name ?? target?.project_id}
              </span>
              . Approving raises that scan&apos;s ceiling only — other scans keep the standard
              allowance.
            </DialogDescription>
          </DialogHeader>

          {target && (
            <div className="space-y-4">
              <div className="rounded-sm border-l-2 border-border bg-muted/40 px-3 py-2">
                <p className="legend mb-1 text-muted-foreground">Stated purpose</p>
                <p className="text-[13px] leading-relaxed text-foreground">{target.reason}</p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="grant" className="legend text-muted-foreground">
                  Grant amount
                </Label>
                <Input
                  id="grant"
                  type="number"
                  min={1}
                  max={500}
                  value={grant}
                  onChange={(e) => setGrant(e.target.value)}
                  aria-invalid={!grantValid}
                />
                <p className="text-[11px] text-muted-foreground">
                  Defaults to what was asked for. Lower it to grant a partial allowance.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="note" className="legend text-muted-foreground">
                  Note (optional)
                </Label>
                <Textarea
                  id="note"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="Visible to the requester alongside your decision."
                  className="min-h-16"
                />
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              disabled={decide.isPending}
              onClick={() => target && decide.mutate({ id: target.id, approve: false })}
            >
              <X /> Reject
            </Button>
            <Button
              disabled={decide.isPending || !grantValid}
              onClick={() => target && decide.mutate({ id: target.id, approve: true })}
            >
              <Check /> {decide.isPending ? "Saving…" : "Approve"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

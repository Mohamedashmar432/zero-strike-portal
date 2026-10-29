"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, ShieldCheck, Undo2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { FilterBar } from "@/components/common/filter-bar";
import { MetricStrip } from "@/components/common/metric-strip";
import { PageHeader } from "@/components/layout/page-header";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import {
  type FindingReviewItem,
  decideFindingReview,
  listFindingReviews,
  revokeFindingReview,
} from "@/lib/api/finding-reviews";
import { queryKeys } from "@/lib/api/query-keys";
import type { ReviewStatus } from "@/lib/api/vulnerabilities";
import { cn } from "@/lib/utils";

const STATUS_TAG: Record<ReviewStatus, string> = {
  pending: "border-severity-medium bg-severity-medium-tint text-severity-medium",
  accepted: "border-status-success bg-status-success-tint text-status-success",
  rejected: "border-severity-critical bg-severity-critical-tint text-severity-critical",
  revoked: "border-severity-high bg-severity-high-tint text-severity-high",
};

const KIND_LABEL = { false_positive: "False positive", accepted_risk: "Accepted risk" } as const;

type Action = { item: FindingReviewItem; mode: "decide" | "revoke" };

export default function FindingReviewsPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<ReviewStatus>("pending");
  const [search, setSearch] = useState("");
  const [action, setAction] = useState<Action | null>(null);
  const [comment, setComment] = useState("");

  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.admin.findingReviews(filter),
    queryFn: () => listFindingReviews(filter),
  });

  function done(message: string) {
    toast.success(message);
    setAction(null);
    setComment("");
    qc.invalidateQueries({ queryKey: ["admin", "finding-reviews"] });
  }
  const onError = (err: unknown) =>
    toast.error(err instanceof ApiError ? err.message : "Could not record the decision.");

  const decide = useMutation({
    mutationFn: ({ id, accept }: { id: string; accept: boolean }) =>
      decideFindingReview(id, { decision: accept ? "accept" : "reject", ...(comment.trim() ? { comment: comment.trim() } : {}) }),
    onSuccess: (r) =>
      done(
        r.review.status === "accepted"
          ? "Accepted. The next CI run reports this finding but no longer counts it."
          : "Rejected. The finding keeps blocking CI."
      ),
    onError,
  });
  const revoke = useMutation({
    mutationFn: (id: string) => revokeFindingReview(id, comment.trim()),
    onSuccess: () => done("Revoked. The finding blocks CI again from the next run."),
    onError,
  });

  const items = (data?.items ?? []).filter((r) => {
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return [r.project_name, r.requested_by_email, r.rule_name, r.rule_id, r.review.file_path, r.review.request_comment]
      .some((v) => (v ?? "").toLowerCase().includes(q));
  });

  const busy = decide.isPending || revoke.isPending;
  const target = action?.item;

  return (
    <div className="space-y-7">
      <div className="signal-in">
        <PageHeader
          eyebrow="Administration / Requests"
          title="Finding Reviews"
          description="Members ask for a finding to stop blocking CI: a false positive for code findings, an accepted risk for dependency findings. While admin review is required (Settings > General), nothing changes until you accept; when it is off, requests are accepted automatically and appear here as accepted, where you can still revoke them. An accepted finding is still detected and reported, at that file only, but the pipeline gate no longer counts it."
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
            { label: "In this view", value: items.length.toLocaleString(), hint: `Status: ${filter}` },
          ]}
        />
      </div>

      <div className="signal-in space-y-3" style={{ "--d": "120ms" } as React.CSSProperties}>
        <FilterBar
          search={search}
          onSearchChange={setSearch}
          searchPlaceholder="Project, requester, rule, file or reason…"
          facets={[
            {
              type: "select",
              value: filter,
              onChange: (v) => setFilter(v as ReviewStatus),
              placeholder: "Status",
              options: [
                { value: "pending", label: "Pending" },
                { value: "accepted", label: "Accepted" },
                { value: "rejected", label: "Rejected" },
                { value: "revoked", label: "Revoked" },
              ],
            },
          ]}
        />

        <DataTableCard
          isLoading={isLoading}
          isError={isError}
          errorMessage="Failed to load finding reviews."
          isEmpty={items.length === 0}
          emptyState={
            <EmptyState
              icon={ShieldCheck}
              title={filter === "pending" ? "Nothing awaiting review" : "No reviews match"}
              description={
                filter === "pending"
                  ? "Requests appear here when a member marks a finding as a false positive, or a dependency finding as an accepted risk."
                  : "Try a different status or clear the search."
              }
            />
          }
        >
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Finding</TableHead>
                <TableHead>Project</TableHead>
                <TableHead>Request</TableHead>
                <TableHead>Reason given</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-36">
                  <span className="sr-only">Action</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.map((r) => (
                <TableRow key={r.vulnerability_id}>
                  <TableCell className="max-w-[18rem] whitespace-normal">
                    <div className="flex items-center gap-2">
                      {r.severity && <SeverityBadge severity={r.severity} />}
                      <span className="text-[13px] font-semibold text-foreground">{r.rule_name ?? r.rule_id}</span>
                    </div>
                    <span className="mt-0.5 block break-all font-mono text-[11px] text-muted-foreground">
                      {r.review.file_path}
                      {r.location?.start_line ? `:${r.location.start_line}` : ""}
                    </span>
                  </TableCell>
                  <TableCell>
                    {r.project_name ? (
                      <Link
                        href={`/projects/${r.project_id}/vulnerabilities/${r.vulnerability_id}`}
                        className="font-mono text-[13px] font-semibold text-foreground underline-offset-4 transition-colors hover:text-signal hover:underline"
                      >
                        {r.project_name}
                      </Link>
                    ) : (
                      <span className="font-mono text-[11px] text-muted-foreground">deleted project</span>
                    )}
                  </TableCell>
                  <TableCell className="text-[13px]">
                    {KIND_LABEL[r.review.kind]}
                    <span className="block font-mono text-[11px] text-muted-foreground">
                      {r.requested_by_email ?? "unknown"} · {new Date(r.review.requested_at).toLocaleString()}
                    </span>
                  </TableCell>
                  <TableCell className="max-w-[24rem] whitespace-normal text-[13px] leading-relaxed text-muted-foreground">
                    {r.review.request_comment}
                  </TableCell>
                  <TableCell>
                    <span className={cn("legend rounded-sm border-l-2 px-1.5 py-0.5", STATUS_TAG[r.review.status])}>
                      {r.review.status}
                    </span>
                    {r.review.reviewed_at && (
                      <span className="mt-0.5 block max-w-56 whitespace-normal text-[11px] leading-snug text-muted-foreground">
                        {r.reviewed_by_email ?? "admin"}
                        {r.review.review_comment ? `: “${r.review.review_comment}”` : ""}
                      </span>
                    )}
                  </TableCell>
                  <TableCell>
                    {r.review.status === "pending" && (
                      <Button size="sm" variant="outline" onClick={() => setAction({ item: r, mode: "decide" })}>
                        Review
                      </Button>
                    )}
                    {r.review.status === "accepted" && (
                      <Button size="sm" variant="outline" onClick={() => setAction({ item: r, mode: "revoke" })}>
                        <Undo2 /> Revoke
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </DataTableCard>
      </div>

      <Dialog
        open={action !== null}
        onOpenChange={(o) => {
          if (!o) {
            setAction(null);
            setComment("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{action?.mode === "revoke" ? "Revoke exemption" : `Review ${target ? KIND_LABEL[target.review.kind].toLowerCase() : ""} request`}</DialogTitle>
            <DialogDescription>
              {action?.mode === "revoke"
                ? "The finding goes back to open and blocks CI again from the next pipeline run."
                : "Accepting stops this finding counting in CI, in this file only. The scanner keeps reporting it, so the decision stays visible."}
            </DialogDescription>
          </DialogHeader>

          {target && (
            <div className="space-y-4">
              <div className="space-y-1 rounded-sm border-l-2 border-border bg-muted/40 px-3 py-2">
                <p className="text-[13px] font-semibold text-foreground">
                  {target.rule_name ?? target.rule_id} <span className="font-mono text-[11px] font-normal text-muted-foreground">in {target.review.file_path}</span>
                </p>
                {target.message && <p className="text-[13px] text-muted-foreground">{target.message}</p>}
                <p className="legend pt-1 text-muted-foreground">Reason from {target.requested_by_email ?? "the requester"}</p>
                <p className="text-[13px] leading-relaxed text-foreground">{target.review.request_comment}</p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="review-comment" className="legend text-muted-foreground">
                  Comment {action?.mode === "decide" ? "(required to reject)" : "(required)"}
                </Label>
                <Textarea
                  id="review-comment"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Shown to the requester and kept in the audit log."
                  className="min-h-16"
                />
              </div>
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setAction(null)}>
              Cancel
            </Button>
            {action?.mode === "revoke" ? (
              <Button
                variant="destructive"
                disabled={busy || !comment.trim()}
                onClick={() => target && revoke.mutate(target.vulnerability_id)}
              >
                <Undo2 /> {revoke.isPending ? "Saving…" : "Revoke"}
              </Button>
            ) : (
              <>
                <Button
                  variant="destructive"
                  disabled={busy || !comment.trim()}
                  onClick={() => target && decide.mutate({ id: target.vulnerability_id, accept: false })}
                >
                  <X /> Reject
                </Button>
                <Button disabled={busy} onClick={() => target && decide.mutate({ id: target.vulnerability_id, accept: true })}>
                  <Check /> {decide.isPending ? "Saving…" : "Accept"}
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

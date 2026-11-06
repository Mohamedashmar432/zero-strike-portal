"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Mail, RefreshCw, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { RelativeTime } from "@/components/common/relative-time";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { DeliveryChip } from "@/components/vulnerabilities/delivery-chip";
import { LifecycleChip } from "@/components/vulnerabilities/lifecycle-chip";
import { RequestAckDialog } from "@/components/vulnerabilities/request-ack-dialog";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { saveBlob } from "@/lib/api/auto-fix";
import { ApiError } from "@/lib/api/client";
import { queryKeys } from "@/lib/api/query-keys";
import {
  BATCH_STATE_LABELS,
  acknowledgeAckBatch,
  downloadAckBatch,
  downloadRiskAcceptances,
  listRiskAcceptances,
  resendAckBatch,
  type AckBatch,
  type RiskAcceptanceStatusFilter,
} from "@/lib/api/risk-acknowledgements";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;
const STATUS_TABS: { value: RiskAcceptanceStatusFilter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "accepted", label: "Accepted" },
  { value: "pending", label: "Pending review" },
];

const BATCH_TONE: Record<AckBatch["state"], string> = {
  pending: "border-status-progress bg-status-progress-tint text-status-progress",
  acknowledged: "border-status-success bg-status-success-tint text-status-success",
  superseded: "border-border bg-muted text-muted-foreground",
  expired: "border-severity-medium bg-severity-medium-tint text-severity-medium",
};

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

async function download(fetcher: () => Promise<{ blob: Blob; filename: string | null }>, fallback: string) {
  try {
    const { blob, filename } = await fetcher();
    saveBlob(blob, filename ?? fallback);
  } catch (e) {
    toast.error(errorText(e, "Download failed"));
  }
}

function BatchStrip({
  projectId,
  batch,
  isAdmin,
  isOwner,
}: {
  projectId: string;
  batch: AckBatch;
  isAdmin: boolean;
  isOwner: boolean;
}) {
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["projects", projectId, "risk-acceptances"] });
    qc.invalidateQueries({ queryKey: ["projects", projectId, "risk-acknowledgements"] });
  };
  const resend = useMutation({
    mutationFn: () => resendAckBatch(projectId, batch.id),
    onSuccess: (b) => {
      // Same rule as the first send: say "sent" only for a recipient whose delivery is `sent`.
      const sent = b.recipients.some((r) => r.delivery === "sent");
      toast[sent ? "success" : "warning"](
        sent ? "Resent. A fresh link was issued." : "Not sent. Check the delivery status on this batch."
      );
      refresh();
    },
    onError: (e) => toast.error(errorText(e, "Could not resend")),
  });
  const acknowledge = useMutation({
    mutationFn: () => acknowledgeAckBatch(projectId, batch.id),
    onSuccess: () => {
      toast.success("Acknowledged");
      refresh();
    },
    onError: (e) => toast.error(errorText(e, "Could not acknowledge")),
  });

  const ownerPending = batch.recipients.some((r) => r.is_project_owner && !r.acknowledged_at);
  const canAcknowledge = isOwner && batch.state === "pending" && ownerPending;
  const canResend = isAdmin && (batch.state === "pending" || batch.state === "expired");

  return (
    <section aria-label="Latest acknowledgement request" className="rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <span
          className={cn(
            "inline-flex items-center rounded-sm border-l-2 px-1.5 py-0.5 font-mono text-[11px] font-semibold uppercase leading-none tracking-[0.08em]",
            BATCH_TONE[batch.state]
          )}
        >
          {BATCH_STATE_LABELS[batch.state]}
        </span>
        <DeliveryChip recipients={batch.recipients} />
        <span className="text-xs text-muted-foreground">
          Requested <RelativeTime iso={batch.created_at} />
          {batch.created_by_email ? ` by ${batch.created_by_email}` : ""}
        </span>
        <span className="font-mono text-[11px] text-muted-foreground">
          {batch.recipients_acknowledged}/{batch.recipients.length} acknowledged · {batch.items_current} of{" "}
          {batch.item_count} still current
          {batch.items_superseded > 0 ? ` · ${batch.items_superseded} superseded` : ""}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {canAcknowledge && (
            <Button size="sm" disabled={acknowledge.isPending} onClick={() => acknowledge.mutate()}>
              <ShieldCheck /> {acknowledge.isPending ? "Saving…" : "Acknowledge"}
            </Button>
          )}
          {canResend && (
            <Button size="sm" variant="outline" disabled={resend.isPending} onClick={() => resend.mutate()}>
              <RefreshCw /> {resend.isPending ? "Sending…" : "Resend"}
            </Button>
          )}
          {isAdmin && (
            <>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => download(() => downloadAckBatch(projectId, batch.id, "pdf"), "risk-acceptance.pdf")}
              >
                <Download /> PDF
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => download(() => downloadAckBatch(projectId, batch.id, "csv"), "risk-acceptance.csv")}
              >
                <Download /> CSV
              </Button>
            </>
          )}
        </div>
      </div>
      {batch.state === "superseded" && (
        <p className="border-t border-hairline px-4 py-2 text-xs text-muted-foreground">
          Every finding in this request was re-decided or revoked after it was sent. Send a new request to
          cover the current decisions.
        </p>
      )}
      <details className="border-t border-hairline px-4 py-2 text-xs">
        <summary className="cursor-pointer font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          Recipients ({batch.recipients.length})
        </summary>
        <ul className="mt-2 space-y-1.5">
          {batch.recipients.map((r) => (
            <li key={`${r.email}-${r.is_project_owner}`} className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-mono">
                {r.email}
                {r.is_project_owner ? " (owner)" : ""}
              </span>
              <DeliveryChip recipients={[r]} />
              <span className="text-muted-foreground">
                {r.send_count} send{r.send_count === 1 ? "" : "s"}
                {r.last_sent_at ? <> · last <RelativeTime iso={r.last_sent_at} /></> : null}
              </span>
              <span className="text-muted-foreground">
                {r.acknowledged_at ? (
                  <>
                    Acknowledged <RelativeTime iso={r.acknowledged_at} />
                    {r.acknowledged_via ? ` via ${r.acknowledged_via === "link" ? "email link" : "portal"}` : ""}
                  </>
                ) : r.token_expires_at ? (
                  <>Link expires <RelativeTime iso={r.token_expires_at} /></>
                ) : (
                  "Not acknowledged"
                )}
              </span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

export function RiskAcceptedPanel({
  projectId,
  isAdmin,
  isOwner,
}: {
  projectId: string;
  isAdmin: boolean;
  isOwner: boolean;
}) {
  const [status, setStatus] = useState<RiskAcceptanceStatusFilter>("all");
  const [page, setPage] = useState(1);
  const [requestOpen, setRequestOpen] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: queryKeys.projects.riskAcceptances(projectId, status, page),
    queryFn: () => listRiskAcceptances(projectId, { reviewStatus: status, page, pageSize: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1;
  const accepted = data?.accepted_count ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Review status" className="flex gap-1">
          {STATUS_TABS.map((t) => (
            <Button
              key={t.value}
              size="sm"
              variant={status === t.value ? "secondary" : "ghost"}
              aria-pressed={status === t.value}
              onClick={() => {
                setStatus(t.value);
                setPage(1);
              }}
            >
              {t.label}
              {data && t.value !== "all" && (
                <span className="font-mono text-[11px] text-muted-foreground">
                  {t.value === "accepted" ? data.accepted_count : data.pending_count}
                </span>
              )}
            </Button>
          ))}
        </div>
        <p role="status" aria-live="polite" className="legend text-muted-foreground">
          {data
            ? `${data.accepted_count} accepted · ${data.pending_count} pending · ${data.unacknowledged_count} not acknowledged`
            : ""}
        </p>
        {isAdmin && (
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              disabled={accepted === 0}
              onClick={() => download(() => downloadRiskAcceptances(projectId, "pdf"), "risk-acceptance.pdf")}
            >
              <Download /> PDF preview
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={accepted === 0}
              onClick={() => download(() => downloadRiskAcceptances(projectId, "csv"), "risk-acceptance.csv")}
            >
              <Download /> CSV preview
            </Button>
            <Button size="sm" disabled={accepted === 0} onClick={() => setRequestOpen(true)}>
              <Mail /> Request acknowledgement
            </Button>
          </div>
        )}
      </div>

      {data?.latest_batch && (
        <BatchStrip projectId={projectId} batch={data.latest_batch} isAdmin={isAdmin} isOwner={isOwner} />
      )}

      <DataTableCard
        isLoading={isLoading}
        isError={isError}
        errorMessage="Failed to load accepted risks."
        isEmpty={!!data && data.items.length === 0}
        emptyState={
          <EmptyState
            icon={ShieldCheck}
            title="No accepted risks"
            description="Accepted risk requests appear here with who asked, why, and who approved them."
          />
        }
      >
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Finding</TableHead>
              <TableHead>Justification</TableHead>
              <TableHead>Requested</TableHead>
              <TableHead>Approved</TableHead>
              <TableHead>Acknowledgement</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data?.items.map((r) => (
              <TableRow key={r.vulnerability_id}>
                <TableCell>{r.severity && <SeverityBadge severity={r.severity} />}</TableCell>
                <TableCell className="max-w-64">
                  <Link
                    href={`/projects/${projectId}/vulnerabilities/${r.vulnerability_id}`}
                    className="block truncate text-xs font-semibold underline-offset-4 hover:text-signal hover:underline"
                  >
                    {r.rule_name ?? r.rule_id ?? "Vulnerability"}
                  </Link>
                  <span className="block truncate font-mono text-[11px] text-muted-foreground" title={r.file_path}>
                    {r.file_path}
                  </span>
                  <span className="mt-1 block">
                    <LifecycleChip
                      finding={{
                        status: r.review_status === "accepted" ? "accepted_risk" : "open",
                        resolution_reason: null,
                        fix_status: r.review_status === "accepted" ? "dismissed" : "open",
                        review: { kind: "accepted_risk", status: r.review_status },
                      }}
                      ack={r.ack_state}
                    />
                  </span>
                </TableCell>
                <TableCell className="max-w-80 whitespace-normal text-xs leading-relaxed text-muted-foreground">
                  {r.comment}
                </TableCell>
                <TableCell className="text-xs">
                  {r.requested_by_email ?? "Unknown"}
                  <span className="block text-muted-foreground">
                    <RelativeTime iso={r.requested_at} />
                  </span>
                </TableCell>
                <TableCell className="text-xs">
                  {r.review_status === "pending" ? (
                    <span className="text-muted-foreground">Awaiting admin</span>
                  ) : (
                    <>
                      {r.auto_accepted ? "Auto-accepted" : (r.reviewed_by_email ?? "Admin")}
                      {r.reviewed_at && (
                        <span className="block text-muted-foreground">
                          <RelativeTime iso={r.reviewed_at} />
                        </span>
                      )}
                    </>
                  )}
                </TableCell>
                <TableCell className="whitespace-normal text-xs">
                  {r.review_status === "pending" ? (
                    <span className="text-muted-foreground">Nothing to acknowledge yet</span>
                  ) : r.ack_state === "acknowledged" ? (
                    <>
                      <span className="font-medium text-status-success">Acknowledged</span>
                      <span className="block text-muted-foreground">
                        {r.acknowledged_by ?? "Recipient"}
                        {r.acknowledged_at && (
                          <>
                            {" "}
                            <RelativeTime iso={r.acknowledged_at} />
                          </>
                        )}
                      </span>
                    </>
                  ) : r.ack_state === "awaiting" ? (
                    <span className="font-medium text-status-progress">Awaiting acknowledgement</span>
                  ) : (
                    <span className="text-muted-foreground">Not requested</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </DataTableCard>

      {data && data.total > PAGE_SIZE && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">
            Page {page} of {totalPages}
          </span>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage(page + 1)}>
              Next
            </Button>
          </div>
        </div>
      )}

      {isAdmin && (
        <RequestAckDialog
          projectId={projectId}
          open={requestOpen}
          onOpenChange={setRequestOpen}
          acceptedCount={accepted}
        />
      )}
    </div>
  );
}

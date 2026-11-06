"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { useState } from "react";
import { DeliveryChip } from "@/components/vulnerabilities/delivery-chip";
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
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/api/client";
import { listMembers } from "@/lib/api/project-members";
import { queryKeys } from "@/lib/api/query-keys";
import {
  MAX_ACK_MESSAGE_CHARS,
  MAX_EXTRA_RECIPIENTS,
  addRecipients,
  createAckBatch,
  deliverySummary,
  recipientCount,
  type AckBatch,
} from "@/lib/api/risk-acknowledgements";

type Step = "compose" | "confirm" | "result";

/**
 * Admin-only. Compose (extra recipients + optional message), then an explicit confirm step that names
 * how many people receive the findings, then the outcome. The outcome only says "sent" for a recipient
 * whose delivery is `sent`; with SMTP unset it says the email was not configured.
 */
export function RequestAckDialog({
  projectId,
  open,
  onOpenChange,
  acceptedCount,
}: {
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  acceptedCount: number;
}) {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("compose");
  const [extra, setExtra] = useState<string[]>([]);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [batch, setBatch] = useState<AckBatch | null>(null);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setStep("compose");
    setExtra([]);
    setDraft("");
    setNotice(null);
    setMessage("");
    setBatch(null);
    setError(null);
  }

  // Same cached members list the project layout already loads; only the owner's address is used.
  const members = useQuery({
    queryKey: queryKeys.projects.members(projectId),
    queryFn: () => listMembers(projectId),
    enabled: open,
  });
  const ownerEmail = members.data?.find((m) => m.role === "owner")?.invited_email;

  const send = useMutation({
    mutationFn: () => createAckBatch(projectId, { extra_recipients: extra, message: message.trim() || null }),
    onSuccess: (b) => {
      setBatch(b);
      setStep("result");
      setError(null);
      qc.invalidateQueries({ queryKey: ["projects", projectId, "risk-acceptances"] });
      qc.invalidateQueries({ queryKey: ["projects", projectId, "risk-acknowledgements"] });
    },
    onError: (e) => {
      setError(e instanceof ApiError ? e.message : "Could not create the request.");
      setStep("compose");
    },
  });

  /** Turns typed or pasted text into chips; what is not an address stays in the box with a note. */
  function commitDraft(raw: string = draft) {
    if (!raw.trim()) return;
    const { next, invalid, overflow } = addRecipients(extra, raw);
    setExtra(next);
    const problems: string[] = [];
    if (invalid.length) problems.push(`Not an email address: ${invalid.join(", ")}`);
    if (overflow) problems.push(`At most ${MAX_EXTRA_RECIPIENTS} extra recipients`);
    setNotice(problems.join(". ") || null);
    setDraft(invalid.join(" "));
  }

  const total = recipientCount(extra);
  const summary = batch ? deliverySummary(batch.recipients) : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        onOpenChange(o);
        if (!o) reset();
      }}
    >
      <DialogContent>
        {step === "compose" && (
          <>
            <DialogHeader>
              <DialogTitle>Request acknowledgement</DialogTitle>
              <DialogDescription>
                Emails the project owner a PDF and CSV of the {acceptedCount} accepted risk
                {acceptedCount === 1 ? "" : "s"} with a link to acknowledge them. Nothing is sent until you confirm on
                the next step.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              {error && (
                <p role="alert" className="rounded-sm border-l-2 border-severity-high bg-severity-high-tint px-3 py-2 text-xs">
                  {error}
                </p>
              )}
              <div className="space-y-1.5">
                <Label htmlFor="ack-extra">Extra recipients (optional, up to {MAX_EXTRA_RECIPIENTS})</Label>
                <div className="flex flex-wrap gap-1.5">
                  {extra.map((addr) => (
                    <span
                      key={addr}
                      className="inline-flex h-6 items-center gap-1 rounded-sm border border-border bg-card pl-2 font-mono text-[11px]"
                    >
                      {addr}
                      <button
                        type="button"
                        aria-label={`Remove ${addr}`}
                        onClick={() => setExtra(extra.filter((a) => a !== addr))}
                        className="h-full cursor-pointer px-1 text-muted-foreground hover:text-destructive focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <X className="size-3" aria-hidden="true" />
                      </button>
                    </span>
                  ))}
                </div>
                <Input
                  id="ack-extra"
                  inputMode="email"
                  value={draft}
                  disabled={extra.length >= MAX_EXTRA_RECIPIENTS}
                  placeholder="name@example.com, then Enter"
                  onChange={(e) => {
                    const v = e.target.value;
                    // A comma, semicolon or space completes an address.
                    if (/[,;\s]$/.test(v)) commitDraft(v);
                    else setDraft(v);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      commitDraft();
                    } else if (e.key === "Backspace" && !draft && extra.length) setExtra(extra.slice(0, -1));
                  }}
                  onBlur={() => commitDraft()}
                  aria-describedby="ack-extra-help"
                />
                <p id="ack-extra-help" aria-live="polite" className="text-xs text-muted-foreground">
                  {notice ?? "Anyone you add receives the finding details and the justifications."}
                </p>
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="ack-message">Message (optional)</Label>
                <Textarea
                  id="ack-message"
                  value={message}
                  maxLength={MAX_ACK_MESSAGE_CHARS}
                  onChange={(e) => setMessage(e.target.value)}
                  placeholder="Shown in the email and on the acknowledgement page."
                />
                <p className="text-right font-mono text-[11px] text-muted-foreground">
                  {message.length}/{MAX_ACK_MESSAGE_CHARS}
                </p>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button
                disabled={acceptedCount === 0}
                onClick={() => {
                  commitDraft();
                  setStep("confirm");
                }}
              >
                Review and send
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "confirm" && (
          <>
            <DialogHeader>
              <DialogTitle>Send to {total} {total === 1 ? "person" : "people"}?</DialogTitle>
              <DialogDescription>
                {acceptedCount} accepted risk{acceptedCount === 1 ? "" : "s"} (rule, file, severity and the written
                justification) will be emailed outside the portal to the project owner
                {extra.length > 0 ? ` and ${extra.length} other ${extra.length === 1 ? "address" : "addresses"}` : ""}.
                Check that each recipient may see this project&apos;s findings.
              </DialogDescription>
            </DialogHeader>
            <ul className="space-y-0.5 font-mono text-xs">
              <li>{ownerEmail ? `${ownerEmail} (owner)` : "Project owner"}</li>
              {extra.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
            <DialogFooter>
              <Button variant="outline" disabled={send.isPending} onClick={() => setStep("compose")}>
                Back
              </Button>
              <Button disabled={send.isPending} onClick={() => send.mutate()}>
                {send.isPending ? "Sending…" : `Send to ${total}`}
              </Button>
            </DialogFooter>
          </>
        )}

        {step === "result" && batch && summary && (
          <>
            <DialogHeader>
              <DialogTitle>Request recorded</DialogTitle>
              <DialogDescription>
                {summary.tone === "sent"
                  ? "The email was handed to the mail server for every recipient."
                  : summary.tone === "partial"
                    ? "Some recipients were not reached. Use Resend on the batch to retry."
                    : summary.tone === "not_configured"
                      ? "No email was sent because outgoing email is not configured for this portal. The request is recorded; configure SMTP, then resend."
                      : "No email went out. The request is recorded; resend it once the problem is fixed."}
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-2">
              <DeliveryChip recipients={batch.recipients} />
              <ul className="space-y-1 text-xs">
                {batch.recipients.map((r) => (
                  <li key={r.email} className="flex items-center justify-between gap-2 font-mono">
                    <span className="truncate">
                      {r.email}
                      {r.is_project_owner ? " (owner)" : ""}
                    </span>
                    <DeliveryChip recipients={[r]} />
                  </li>
                ))}
              </ul>
            </div>
            <DialogFooter>
              <Button onClick={() => onOpenChange(false)}>Done</Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

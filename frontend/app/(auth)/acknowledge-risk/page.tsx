"use client";

import { ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/api/client";
import {
  acknowledgeByToken,
  lookupAckToken,
  tokenFromHash,
  type PublicAckLookup,
} from "@/lib/api/risk-acknowledgements";
import { parseApiDate } from "@/lib/utils";

type Phase =
  | { kind: "loading" }
  | { kind: "missing" }
  | { kind: "invalid" }
  | { kind: "limited" }
  | { kind: "error" }
  | { kind: "ready"; data: PublicAckLookup }
  | { kind: "done"; projectName: string; itemCount: number };

/**
 * Public acknowledgement page (no sign-in). The one-time token is in the URL fragment
 * (#token=...), so it is never sent in a request line, a server log or a Referer header; it is read
 * here, kept in memory, and removed from the address bar. It lives in the (auth) route group, which
 * has no session guard, and uses plain fetch so a failure cannot trigger the sign-in redirect.
 *
 * A bad, used or expired link all look the same by design: the page must not reveal which tokens exist.
 */
export default function AcknowledgeRiskPage() {
  const [token, setToken] = useState<string | null>(null);
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // StrictMode runs the effect twice in dev; the first run strips the fragment, so the token is read
  // once and the second run reuses it instead of seeing an empty hash.
  const tokenRef = useRef<string | null | undefined>(undefined);

  useEffect(() => {
    if (tokenRef.current === undefined) tokenRef.current = tokenFromHash(window.location.hash);
    const t = tokenRef.current;
    if (!t) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setPhase({ kind: "missing" });
      return;
    }
    setToken(t);
    // Drop the fragment so the token is not left in the address bar or history entry.
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    let cancelled = false;
    lookupAckToken(t)
      .then((data) => !cancelled && setPhase({ kind: "ready", data }))
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) setPhase({ kind: "invalid" });
        else if (e instanceof ApiError && e.status === 429) setPhase({ kind: "limited" });
        else setPhase({ kind: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function acknowledge() {
    if (!token) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const r = await acknowledgeByToken(token);
      setToken(null);
      setPhase({ kind: "done", projectName: r.project_name, itemCount: r.item_count });
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) setPhase({ kind: "invalid" });
      else if (e instanceof ApiError && e.status === 429) setSubmitError("Too many attempts. Wait a few minutes and try again.");
      else setSubmitError("Could not record your acknowledgement. Try again.");
    } finally {
      setSubmitting(false);
    }
  }

  // The auth layout is a narrow column for forms; this page lists findings, so it breaks out of it.
  return (
    <div className="relative left-1/2 w-[min(46rem,calc(100vw-2.5rem))] -translate-x-1/2">
      <Card>
        {phase.kind === "loading" && (
          <CardHeader>
            <CardTitle>Checking your link…</CardTitle>
          </CardHeader>
        )}

        {phase.kind === "missing" && (
          <CardHeader>
            <CardTitle>Link incomplete</CardTitle>
            <CardDescription>
              This page needs the full link from the acknowledgement email. Open it again from the email.
            </CardDescription>
          </CardHeader>
        )}

        {phase.kind === "invalid" && (
          <CardHeader>
            <CardTitle>This link is not valid</CardTitle>
            <CardDescription>
              It may have already been used, have expired, or been replaced by a newer request. Ask the portal
              administrator to send a new one.
            </CardDescription>
          </CardHeader>
        )}

        {phase.kind === "limited" && (
          <CardHeader>
            <CardTitle>Too many attempts</CardTitle>
            <CardDescription>Wait a few minutes, then open the link from your email again.</CardDescription>
          </CardHeader>
        )}

        {phase.kind === "error" && (
          <CardHeader>
            <CardTitle>Could not load this request</CardTitle>
            <CardDescription>The portal could not be reached. Reload the page or try again shortly.</CardDescription>
          </CardHeader>
        )}

        {phase.kind === "done" && (
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="size-5 text-status-success" aria-hidden="true" /> Acknowledged
            </CardTitle>
            <CardDescription role="status">
              Thank you. You acknowledged {phase.itemCount} accepted risk{phase.itemCount === 1 ? "" : "s"} in{" "}
              {phase.projectName}. This link can no longer be used.
            </CardDescription>
          </CardHeader>
        )}

        {phase.kind === "ready" && (
          <>
            <CardHeader>
              <CardTitle>Acknowledge accepted risks</CardTitle>
              <CardDescription>
                {phase.data.item_count} finding{phase.data.item_count === 1 ? "" : "s"} in{" "}
                <span className="font-semibold text-foreground">{phase.data.project_name}</span> were accepted as
                risks. Requested {parseApiDate(phase.data.created_at).toLocaleDateString()}
                {phase.data.expires_at
                  ? `; this link works until ${parseApiDate(phase.data.expires_at).toLocaleDateString()}`
                  : ""}
                .
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {phase.data.message && (
                <p className="rounded-sm border-l-2 border-border bg-muted/40 px-3 py-2 text-sm">{phase.data.message}</p>
              )}
              <ul className="max-h-[22rem] space-y-2 overflow-y-auto pr-1" aria-label="Accepted risks">
                {phase.data.items.map((i, idx) => (
                  <li key={idx} className="rounded-sm border border-hairline px-3 py-2">
                    <div className="flex flex-wrap items-center gap-2">
                      {i.severity && <SeverityBadge severity={i.severity} />}
                      <span className="text-sm font-semibold">{i.rule_name ?? "Finding"}</span>
                    </div>
                    <p className="break-all font-mono text-[11px] text-muted-foreground">{i.file_path}</p>
                    <p className="mt-1 text-xs leading-relaxed">{i.comment}</p>
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                      {i.auto_accepted ? "Auto-accepted" : "Approved"}
                      {i.accepted_at ? ` ${parseApiDate(i.accepted_at).toLocaleDateString()}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
              {phase.data.item_count > phase.data.items.length && (
                <p className="text-xs text-muted-foreground">
                  Showing {phase.data.items.length} of {phase.data.item_count}. The PDF and CSV attached to the email
                  list every finding.
                </p>
              )}
              {submitError && (
                <p role="alert" className="text-sm text-destructive">
                  {submitError}
                </p>
              )}
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs text-muted-foreground">
                  Acknowledging records that you have seen these decisions. It does not change any finding.
                </p>
                <Button onClick={acknowledge} disabled={submitting}>
                  {submitting ? "Saving…" : "Acknowledge"}
                </Button>
              </div>
            </CardContent>
          </>
        )}
      </Card>
    </div>
  );
}

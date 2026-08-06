"use client";

/**
 * The original scanner finding behind a proposal — deliberately kept visually distinct from the
 * AI-generated content beside it. The scanner is an independent tool; a reviewer needs to be able to
 * tell "this is what was detected" from "this is what a model wrote about it".
 */

import { CodeSnippet } from "@/components/findings/code-snippet";
import { SeverityBadge } from "@/components/severity/severity-badge";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { AiFixProposal } from "@/lib/api/auto-fix";
import type { Finding } from "@/lib/api/findings";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

export function EvidencePanel({
  proposal,
  finding,
  isLoading,
}: {
  proposal: AiFixProposal;
  finding: Finding | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  // The finding list is scan-scoped and paginated; a proposal whose finding isn't in the page still
  // renders from the context the proposal itself echoes, rather than showing an error.
  if (!finding) {
    return (
      <div className="space-y-3">
        <dl className="space-y-2">
          <Row label="Rule">{proposal.finding_rule_name ?? "—"}</Row>
          <Row label="Location">
            <span className="font-mono text-xs">
              {proposal.finding_file ?? "—"}
              {proposal.finding_start_line ? `:${proposal.finding_start_line}` : ""}
            </span>
          </Row>
        </dl>
        <p className="text-sm text-muted-foreground">
          Full scanner evidence isn&apos;t loaded for this finding. Open the scan detail page to see it.
        </p>
      </div>
    );
  }

  const ev = finding.evidence?.[0];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {finding.severity && <SeverityBadge severity={finding.severity} />}
        {finding.kind && (
          <Badge variant="outline" className="uppercase">
            {finding.kind}
          </Badge>
        )}
        {finding.language && <Badge variant="outline">{finding.language}</Badge>}
        <span className="text-xs text-muted-foreground">detected by the ZeroStrike scanner</span>
      </div>

      <p className="text-sm">{finding.message}</p>

      <dl className="space-y-2">
        <Row label="Rule">
          {finding.rule_name ?? "—"}
          {finding.rule_id && <span className="ml-2 font-mono text-xs text-muted-foreground">{finding.rule_id}</span>}
        </Row>
        <Row label="Location">
          <span className="font-mono text-xs">
            {finding.location.file}
            {finding.location.start_line ? `:${finding.location.start_line}` : ""}
          </span>
        </Row>
        {!!finding.cwe.length && (
          <Row label="CWE">
            <span className="flex flex-wrap gap-1">
              {finding.cwe.map((c) => (
                <Badge key={c} variant="outline" className="font-mono text-xs">
                  {c}
                </Badge>
              ))}
            </span>
          </Row>
        )}
        {!!finding.owasp.length && (
          <Row label="OWASP">
            <span className="flex flex-wrap gap-1">
              {finding.owasp.map((o) => (
                <Badge key={o} variant="outline" className="font-mono text-xs">
                  {o}
                </Badge>
              ))}
            </span>
          </Row>
        )}
        {finding.fingerprint && (
          <Row label="Fingerprint">
            <span className="font-mono text-xs text-muted-foreground">{finding.fingerprint}</span>
          </Row>
        )}
        {finding.dependency?.package && (
          <Row label="Package">
            <span className="font-mono text-xs">
              {finding.dependency.package} {finding.dependency.installed_version}
              {finding.dependency.fixed_version && ` → fixed in ${finding.dependency.fixed_version}`}
            </span>
          </Row>
        )}
      </dl>

      {ev?.snippet && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Flagged code</p>
          <CodeSnippet
            snippet={ev.snippet}
            snippetStartLine={ev.start_line}
            highlightStart={finding.location.start_line}
            highlightEnd={finding.location.end_line}
          />
        </div>
      )}

      {finding.taint_context?.sink && (
        <div className="space-y-1 rounded-md border bg-muted/20 px-3 py-2">
          <p className="text-xs font-medium text-muted-foreground">Taint flow</p>
          <p className="font-mono text-xs">
            {finding.taint_context.source_expr ?? finding.taint_context.source_var ?? "source"}{" "}
            <span aria-hidden>→</span> {finding.taint_context.sink}
          </p>
        </div>
      )}

      {finding.rationale && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Why the scanner flagged this</p>
          <p className="text-sm text-muted-foreground">{finding.rationale}</p>
        </div>
      )}

      {finding.remediation && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Scanner guidance</p>
          <p className="text-sm text-muted-foreground">{finding.remediation}</p>
        </div>
      )}

      {!!finding.references.length && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">References</p>
          <ul className="space-y-0.5">
            {finding.references.map((r) => (
              <li key={r}>
                <a
                  href={r}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-brand underline underline-offset-2 break-all"
                >
                  {r}
                </a>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

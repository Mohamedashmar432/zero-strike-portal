"use client";

/**
 * Why this proposal is in its review_state, from the three per-stage artifacts the backend persists:
 * triage (deterministic, pre-LLM), critique (post-draft AI review), validation (scanner re-scan).
 *
 * Rendered as pipeline steps because that is what they are — each one can independently stop a fix,
 * and a reviewer's first question is always "which one stopped it, and why".
 */

import { CircleDashed, CircleSlash, ShieldCheck, TriangleAlert } from "lucide-react";
import type { AiFixProposal, FixCritique, FixTriage, FixValidation } from "@/lib/api/auto-fix";
import { cn } from "@/lib/utils";

type Tone = "ok" | "warn" | "bad" | "idle";

const TONE: Record<Tone, string> = {
  ok: "text-emerald-500",
  warn: "text-severity-medium",
  bad: "text-severity-critical",
  idle: "text-muted-foreground",
};

const ICON = { ok: ShieldCheck, warn: TriangleAlert, bad: CircleSlash, idle: CircleDashed };

function Step({
  label,
  tone,
  headline,
  children,
}: {
  label: string;
  tone: Tone;
  headline: string;
  children?: React.ReactNode;
}) {
  const Icon = ICON[tone];
  return (
    <li className="flex gap-3">
      <Icon className={cn("mt-0.5 size-4 shrink-0", TONE[tone])} aria-hidden />
      <div className="min-w-0 space-y-1">
        <p className="text-sm">
          <span className="font-medium">{label}</span>
          <span className="text-muted-foreground"> — {headline}</span>
        </p>
        {children}
      </div>
    </li>
  );
}

const STRATEGY_LABEL: Record<string, string> = {
  "rotate-secret": "rotate the credential",
  "dependency-bump": "dependency version bump",
  "code-patch": "code patch",
  none: "no automated action",
};

function TriageStep({ triage }: { triage: FixTriage }) {
  if (triage.eligible !== false) {
    return <Step label="Triage" tone="ok" headline={`eligible for an automated ${STRATEGY_LABEL[triage.strategy ?? "code-patch"] ?? "fix"}`} />;
  }
  return (
    <Step
      label="Triage"
      tone="warn"
      headline={`not automatically fixable — ${STRATEGY_LABEL[triage.strategy ?? "none"] ?? "manual remediation"}`}
    >
      {triage.reason && <p className="text-sm text-muted-foreground">{triage.reason}</p>}
      <p className="text-xs text-muted-foreground">
        Checked before any AI call, so no tokens were spent on this finding.
      </p>
    </Step>
  );
}

// Why no critique ran. "unavailable" is the only one that means a patch exists but went unreviewed —
// the others must not be phrased as a warning about an unreviewed patch, because there is no patch.
const SKIP_REASON: Record<string, string> = {
  disabled: "The review pass is turned off in Auto-Fix settings.",
  no_patch: "There was no patch to review — the AI did not produce one for this finding.",
  unavailable: "The reviewer was unavailable. The patch below is unreviewed — read it carefully.",
};

function CritiqueStep({ critique }: { critique: FixCritique }) {
  // "skipped" must never read as a pass — the patch simply was not reviewed.
  if (critique.skipped) {
    return (
      <Step label="AI review" tone="idle" headline="not performed">
        <p className="text-xs text-muted-foreground">
          {SKIP_REASON[critique.skipped] ?? SKIP_REASON.unavailable}
        </p>
      </Step>
    );
  }
  if (!critique.verdict) return null;

  const tone: Tone = critique.verdict === "pass" ? "ok" : critique.verdict === "reject" ? "bad" : "warn";
  const headline =
    critique.verdict === "pass"
      ? "the patch was reviewed and looks correct"
      : critique.verdict === "reject"
        ? "the reviewer rejected this patch"
        : "the reviewer asked for changes";

  return (
    <Step label="AI review" tone={tone} headline={headline}>
      {critique.reasoning && <p className="text-sm text-muted-foreground">{critique.reasoning}</p>}
      {!!critique.issues?.length && (
        <ul className="list-disc space-y-0.5 pl-4 text-sm text-muted-foreground">
          {critique.issues.map((issue) => (
            <li key={issue}>{issue}</li>
          ))}
        </ul>
      )}
      <p className="text-xs text-muted-foreground">
        {typeof critique.adjusted_confidence === "number" &&
          `Reviewer confidence ${Math.round(critique.adjusted_confidence)}%. `}
        {critique.redrafted && "The patch was redrafted once to address this feedback."}
      </p>
    </Step>
  );
}

function ValidationStep({ validation }: { validation: FixValidation }) {
  const cleared = validation.target_cleared;
  const newCount = validation.new_finding_count ?? 0;
  const tone: Tone = cleared && newCount === 0 ? "ok" : "bad";
  return (
    <Step
      label="Scanner validation"
      tone={tone}
      headline={cleared ? "the finding is resolved on re-scan" : "the finding was NOT resolved on re-scan"}
    >
      <ul className="space-y-0.5 text-sm text-muted-foreground">
        <li>New findings introduced: {newCount}</li>
        {validation.scope_ok !== undefined && (
          <li>Changed only the proposed file: {validation.scope_ok ? "yes" : "no"}</li>
        )}
        {typeof validation.baseline_count === "number" && typeof validation.post_count === "number" && (
          <li>
            Findings before → after: {validation.baseline_count} → {validation.post_count}
          </li>
        )}
        {validation.scanner_version && <li className="font-mono text-xs">scanner {validation.scanner_version}</li>}
      </ul>
      <p className="text-xs text-muted-foreground">
        Run by the real ZeroStrike scanner on a fresh clone — not an AI judgement.
      </p>
    </Step>
  );
}

export function FixStagePanel({ proposal }: { proposal: AiFixProposal }) {
  const { triage, critique, validation } = proposal;
  if (!triage && !critique && !validation) {
    return (
      <p className="text-sm text-muted-foreground">
        No pipeline details were recorded for this proposal. Regenerate the fix to capture them.
      </p>
    );
  }
  return (
    <ol className="space-y-3">
      {triage && <TriageStep triage={triage} />}
      {critique && <CritiqueStep critique={critique} />}
      {validation && <ValidationStep validation={validation} />}
      {!validation && proposal.can_fix && (
        <Step
          label="Scanner validation"
          tone="idle"
          headline="runs when you create the pull request"
        >
          <p className="text-xs text-muted-foreground">
            The patch is applied to a fresh clone and re-scanned; the PR is only opened if the finding
            clears and nothing new appears.
          </p>
        </Step>
      )}
    </ol>
  );
}

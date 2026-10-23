"use client";

import Link from "next/link";
import { FAIL_ON_OPTIONS, type FailOn } from "@/lib/cicd-fail-on";
import { cn } from "@/lib/utils";

type Outcome = "pass" | "warn" | "fail";

// What the pipeline does for each situation under each gate. Mirrors findingsGateLines and the
// hosted Classic script: critical/high raise a warning, the gate decides whether that fails the run.
const SCENARIOS: { label: string; outcome: Record<FailOn, Outcome> }[] = [
  { label: "Critical finding", outcome: { none: "warn", critical: "fail", high: "fail" } },
  { label: "High finding (no critical)", outcome: { none: "warn", critical: "warn", high: "fail" } },
  { label: "Medium / low only", outcome: { none: "pass", critical: "pass", high: "pass" } },
  { label: "Scan error (token, download, upload)", outcome: { none: "fail", critical: "fail", high: "fail" } },
];

const OUTCOME_STYLE: Record<Outcome, { text: string; className: string }> = {
  pass: { text: "Pass", className: "bg-muted text-foreground" },
  warn: { text: "Warn", className: "bg-severity-medium-tint text-severity-medium" },
  fail: { text: "Fail", className: "bg-severity-critical-tint text-severity-critical" },
};

/**
 * Explains ZEROSTRIKE_FAIL_ON and lets the engineer pick the value baked into the snippet. The project
 * setting is only the default; changing it here affects the copied snippet, not the project.
 */
export function GateReference({
  value,
  projectDefault,
  onChange,
  projectId,
}: {
  value: FailOn;
  projectDefault: FailOn;
  onChange: (v: FailOn) => void;
  projectId: string;
}) {
  return (
    <aside className="space-y-4 rounded-lg border border-border p-4 text-xs">
      <div className="space-y-1">
        <p className="font-heading text-sm font-medium text-foreground">Pipeline gate</p>
        <p className="text-muted-foreground">
          <code className="font-mono text-foreground">ZEROSTRIKE_FAIL_ON</code> decides which findings fail the
          build. Pick one to update the snippet.
        </p>
      </div>

      <div role="radiogroup" aria-label="Pipeline gate" className="space-y-1.5">
        {FAIL_ON_OPTIONS.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={value === o.value}
            onClick={() => onChange(o.value)}
            className={cn(
              "w-full rounded-md border px-3 py-2 text-left transition-colors",
              value === o.value ? "border-primary/60 bg-accent" : "border-border hover:border-primary/30"
            )}
          >
            <span className="flex items-center justify-between gap-2">
              <code className="font-mono text-foreground">{o.value}</code>
              {o.value === projectDefault && <span className="text-muted-foreground">project default</span>}
            </span>
            <span className="mt-0.5 block text-muted-foreground">{o.description}</span>
          </button>
        ))}
      </div>

      <table className="w-full">
        <caption className="pb-1.5 text-left text-muted-foreground">
          With <code className="font-mono text-foreground">{value}</code>, the run will:
        </caption>
        <tbody className="divide-y divide-border">
          {SCENARIOS.map((s) => {
            const o = OUTCOME_STYLE[s.outcome[value]];
            return (
              <tr key={s.label}>
                <td className="py-1.5 pr-2 text-muted-foreground">{s.label}</td>
                <td className="py-1.5 text-right">
                  <span className={cn("rounded px-1.5 py-0.5 font-mono text-[11px] font-medium", o.className)}>
                    {o.text}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      <dl className="space-y-1 border-t border-border pt-3 text-muted-foreground">
        <p className="pb-1 font-medium text-foreground">Exit codes</p>
        <div className="flex gap-2"><dt className="w-4 font-mono text-foreground">0</dt><dd>Passed (a warning still shows in the run)</dd></div>
        <div className="flex gap-2"><dt className="w-4 font-mono text-foreground">1</dt><dd>Findings tripped the gate</dd></div>
        <div className="flex gap-2"><dt className="w-4 font-mono text-foreground">2</dt><dd>Setup failed: token, download or upload</dd></div>
      </dl>

      <p className="text-muted-foreground">
        In a YAML snippet the value sits near the top of the file. In a Classic pipeline, a pipeline variable
        named <code className="font-mono text-foreground">ZEROSTRIKE_FAIL_ON</code> overrides it. Change the
        project default in{" "}
        <Link href={`/projects/${projectId}?tab=settings`} className="underline underline-offset-2">
          Project Settings
        </Link>
        .
      </p>
    </aside>
  );
}

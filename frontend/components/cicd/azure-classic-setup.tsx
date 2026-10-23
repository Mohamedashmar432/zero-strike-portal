"use client";

import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { CopyBlock } from "@/components/common/copy-block";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api/client";
import { getScannerBinaryInfo } from "@/lib/api/downloads";
import { azureClassicInlineScript, normalizeOrigin } from "@/lib/cicd/azure-classic";
import type { FailOn } from "@/lib/cicd-fail-on";
import { cn } from "@/lib/utils";

/** A value that copies itself on click; falls back silently if the clipboard is blocked. */
function CopyChip({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title="Click to copy"
      className={`truncate rounded bg-muted px-2 py-1 text-left font-mono text-xs text-foreground hover:bg-muted/70 ${className ?? ""}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {}
      }}
    >
      {copied ? "Copied" : text}
    </button>
  );
}

function Mono({ children }: { children: React.ReactNode }) {
  return <code className="font-mono text-foreground">{children}</code>;
}

/** "Name  Value" pair of copy chips, the shape every Azure DevOps form field takes here. */
function Field({ name, value, note }: { name: string; value: string; note?: string }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <CopyChip text={name} className="w-48" />
      <CopyChip text={value} className="min-w-0 flex-1" />
      {note && <span className="text-xs text-muted-foreground">{note}</span>}
    </div>
  );
}

/**
 * Setup for Azure DevOps Classic (designer) pipelines as a checklist the engineer walks through. The
 * inline script only downloads and runs the portal-hosted script (the inline field caps at 5000
 * characters). Deliberately does not read the project's API keys, so no key name or prefix can end
 * up on this screen.
 */
export function AzureClassicSetup({ origin, failOn, projectId }: { origin: string; failOn: FailOn; projectId: string }) {
  const info = useQuery({
    queryKey: ["scanner-binary-info", "latest", "linux-amd64"],
    queryFn: () => getScannerBinaryInfo("latest", "linux-amd64"),
    retry: false,
  });
  const notPublished = info.error instanceof ApiError && info.error.status === 404;
  const inline = azureClassicInlineScript({ origin, failOn });
  // Progress lives in sessionStorage per project: step 1 sends the engineer off to create a token
  // (same tab), and switching provider unmounts this component; neither should wipe the checklist.
  const storeKey = `azure-classic-steps:${projectId}`;
  const [done, setDoneState] = useState<Set<number>>(() => {
    try {
      return new Set(JSON.parse(sessionStorage.getItem(storeKey) ?? "[]") as number[]);
    } catch {
      return new Set();
    }
  });
  const [open, setOpen] = useState(() => [0, 1, 2, 3, 4].find((i) => !done.has(i)) ?? -1);
  function setDone(next: Set<number>) {
    setDoneState(next);
    try {
      sessionStorage.setItem(storeKey, JSON.stringify([...next]));
    } catch {}
  }

  const steps: { title: string; body: React.ReactNode }[] = [
    {
      title: "Store the project token as a secret variable",
      body: (
        <>
          <p>
            In the pipeline editor open <Mono>Variables</Mono> &gt; <Mono>+ Add</Mono>. Paste the project token as
            the value and click the lock icon so it is secret. The token is shown only once, when it is created
            under{" "}
            <Link href={`/projects/${projectId}?tab=keys`} className="underline underline-offset-2">
              Project Tokens
            </Link>
            .
          </p>
          <Field name="ZEROSTRIKE_TOKEN" value="<paste your project token>" note="secret" />
        </>
      ),
    },
    {
      title: "Add a Bash task on an Ubuntu agent",
      body: (
        <>
          <p>
            On the agent job set the pool to <Mono>Azure Pipelines</Mono> with image <Mono>ubuntu-latest</Mono>.
            Click <Mono>+</Mono>, add a <Mono>Bash</Mono> task after your build and before any deploy, so a failing
            gate stops the release. Then set:
          </p>
          <Field name="Type" value="Inline" />
          <Field name="Working Directory" value="$(Build.SourcesDirectory)" />
        </>
      ),
    },
    {
      title: "Paste the script",
      body: <CopyBlock label="Inline script" text={inline} filename="thinkshield-inline.sh" />,
    },
    {
      title: "Map the token into the task",
      body: (
        <>
          <p>
            Secret variables are not visible to scripts unless mapped. In the Bash task open{" "}
            <Mono>Environment Variables</Mono> and add:
          </p>
          <Field name="ZEROSTRIKE_TOKEN" value="$(ZEROSTRIKE_TOKEN)" />
        </>
      ),
    },
    {
      title: "Save & queue",
      body: (
        <p>
          The run appears under this project&apos;s Scans tab as <Mono>ADO Classic: &lt;pipeline&gt; #&lt;build&gt;</Mono>{" "}
          with a link back to the build. Findings show as red errors in the run; the gate on the right decides
          whether they fail it.
        </p>
      ),
    },
  ];

  function complete(i: number) {
    setDone(new Set(done).add(i));
    setOpen(i + 1);
  }

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="flex items-center gap-3">
            <span>
              {done.size} of {steps.length} steps done
            </span>
            {done.size > 0 && (
              <button
                type="button"
                onClick={() => {
                  setDone(new Set());
                  setOpen(0);
                }}
                className="underline-offset-2 hover:text-foreground hover:underline"
              >
                Start over
              </button>
            )}
          </span>
          <span>
            {info.data
              ? `Scanner: latest (now ${info.data.version})`
              : info.isLoading
                ? "Checking the published scanner…"
                : "Scanner: latest"}
          </span>
        </div>
        <div className="h-1 overflow-hidden rounded bg-muted">
          <div className="h-full bg-primary transition-all" style={{ width: `${(done.size / steps.length) * 100}%` }} />
        </div>
      </div>

      {notPublished && (
        <p className="rounded-lg border border-severity-medium bg-severity-medium-tint p-3 text-xs text-foreground">
          No Linux (amd64) scanner is published on this portal, so the pipeline will fail with HTTP 404 when it
          downloads the scanner. A portal admin must publish it first.
        </p>
      )}

      <ol className="space-y-2">
        {steps.map((s, i) => {
          const isOpen = open === i;
          const isDone = done.has(i);
          return (
            <li key={s.title} className={cn("rounded-lg border", isOpen ? "border-primary/50" : "border-border")}>
              <button
                type="button"
                aria-expanded={isOpen}
                onClick={() => setOpen(isOpen ? -1 : i)}
                className="flex w-full items-center gap-3 px-3 py-2.5 text-left"
              >
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-full border font-mono text-xs",
                    isDone ? "border-primary bg-primary text-primary-foreground" : "border-border text-muted-foreground"
                  )}
                >
                  {isDone ? <Check className="size-3.5" /> : i + 1}
                </span>
                <span className={cn("text-sm font-medium", isDone ? "text-muted-foreground" : "text-foreground")}>
                  {s.title}
                </span>
              </button>
              {isOpen && (
                <div className="space-y-3 px-3 pb-3 pl-12 text-sm text-muted-foreground">
                  {s.body}
                  <div className="flex justify-end">
                    <Button type="button" size="sm" variant={isDone ? "outline" : "default"} onClick={() => complete(i)}>
                      {i === steps.length - 1 ? "Finish" : isDone ? "Next" : "Done, next step"}
                    </Button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ol>

      <details className="rounded-lg border border-border px-3 py-2.5 text-xs text-muted-foreground">
        <summary className="cursor-pointer text-sm font-medium text-foreground">Optional pipeline variables</summary>
        <div className="mt-3 space-y-2">
          <p>Add any of these under Variables to override the script&apos;s defaults without editing it.</p>
          <Field name="ZEROSTRIKE_VERSION" value="latest" note="or pin a release, e.g. v0.41.0" />
          <Field name="ZEROSTRIKE_FAIL_ON" value={failOn} note="none | critical | high" />
          <Field name="ZEROSTRIKE_PORTAL_URL" value={normalizeOrigin(origin)} />
          <p className="pt-1">
            The JSON report is kept at <Mono>$(Agent.TempDirectory)/zerostrike/zerostrike-report.json</Mono>; add a
            Publish build artifacts task for it if you want it on the run. Linux (amd64) agents only; a self-hosted
            agent needs <Mono>curl</Mono>, <Mono>jq</Mono> and <Mono>sha256sum</Mono>. To scan pull requests, add a
            branch policy build validation that runs this pipeline. More in the{" "}
            <Link href="/guide#azure-devops-classic" className="underline underline-offset-2">
              guide
            </Link>
            .
          </p>
        </div>
      </details>
    </div>
  );
}

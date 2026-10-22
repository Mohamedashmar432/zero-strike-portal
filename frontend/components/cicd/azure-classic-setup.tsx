"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { CopyBlock } from "@/components/common/copy-block";
import { ApiError } from "@/lib/api/client";
import { getScannerBinaryInfo } from "@/lib/api/downloads";
import { azureClassicBashScript, normalizeOrigin, VERSION_PLACEHOLDER } from "@/lib/cicd/azure-classic";
import { FAIL_ON_OPTIONS, type FailOn } from "@/lib/cicd-fail-on";
import { useState } from "react";

/** A value that copies itself on click; falls back silently if the clipboard is blocked. */
function CopyChip({ text, className }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      title="Click to copy"
      className={`truncate rounded bg-muted px-2 py-1 text-left font-mono text-foreground hover:bg-muted/70 ${className ?? ""}`}
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

/**
 * Setup for Azure DevOps Classic (designer) pipelines: a Bash task on an Ubuntu agent. The script
 * never contains a token; the user maps their own secret variable into the task. Deliberately does
 * not read the project's API keys, so no key name or prefix can end up on this screen.
 */
export function AzureClassicSetup({
  origin,
  failOn,
  projectId,
}: {
  origin: string;
  failOn: FailOn;
  projectId: string;
}) {
  const info = useQuery({
    queryKey: ["scanner-binary-info", "latest", "linux-amd64"],
    queryFn: () => getScannerBinaryInfo("latest", "linux-amd64"),
    retry: false,
  });
  const notPublished = info.error instanceof ApiError && info.error.status === 404;
  const version = info.data?.version ?? null;
  const script = azureClassicBashScript({ origin, version, failOn });
  const variables: { name: string; value: string | null; hint?: string; secret?: boolean }[] = [
    { name: "ZEROSTRIKE_TOKEN", value: null, hint: "Your project API key (generate under Project Settings > API Keys)", secret: true },
    { name: "ZEROSTRIKE_PORTAL_URL", value: normalizeOrigin(origin) },
    { name: "ZEROSTRIKE_VERSION", value: version ?? VERSION_PLACEHOLDER },
    { name: "ZEROSTRIKE_FAIL_ON", value: failOn },
  ];

  return (
    <div className="space-y-4">
      {info.isLoading ? (
        <p className="text-xs text-muted-foreground">Checking the published scanner version…</p>
      ) : info.data ? (
        <p className="text-xs text-muted-foreground">
          Pinned to {info.data.version} (published {new Date(info.data.uploaded_at).toLocaleDateString()}). Set{" "}
          <Mono>ZEROSTRIKE_VERSION</Mono> to pin a different release.
        </p>
      ) : notPublished ? (
        <p className="rounded-lg border border-severity-medium bg-severity-medium-tint p-3 text-xs text-foreground">
          No Linux (amd64) scanner is published on this portal, so the script will fail with HTTP 404 when it
          downloads the scanner. A portal admin must publish it first. The script is shown below with a{" "}
          <Mono>&lt;ZEROSTRIKE_VERSION&gt;</Mono> placeholder.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">
          Couldn&apos;t check which scanner version is published. Set <Mono>ZEROSTRIKE_VERSION</Mono> yourself.
        </p>
      )}

      <div className="space-y-2">
        <p className="text-sm font-medium text-foreground">Pipeline variables</p>
        <p className="text-xs text-muted-foreground">
          In the pipeline editor open Variables &gt; Pipeline variables and add each row below (copy the name,
          then the value).
        </p>
        <div className="divide-y rounded-lg border text-xs">
          {variables.map((v) => (
            <div key={v.name} className="flex flex-wrap items-center gap-x-4 gap-y-1 p-2.5">
              <CopyChip text={v.name} className="w-56" />
              {v.value !== null ? (
                <CopyChip text={v.value} className="min-w-0 flex-1" />
              ) : (
                <span className="min-w-0 flex-1 text-muted-foreground">{v.hint}</span>
              )}
              {v.secret && <span className="text-muted-foreground">Keep this value secret (lock icon)</span>}
            </div>
          ))}
        </div>
      </div>

      <ol className="list-decimal space-y-2 pl-5 text-sm text-muted-foreground">
        <li>
          Add the variables above. The token is shown only once, when the project API key is created
          (Project Settings &gt; API Keys); generate one there and paste it as the{" "}
          <Mono>ZEROSTRIKE_TOKEN</Mono> value. Never paste it into the script.
        </li>
        <li>
          Add a <Mono>Bash</Mono> task with Type <Mono>Inline</Mono> and Working Directory{" "}
          <Mono>$(Build.SourcesDirectory)</Mono>, and paste the script below.
        </li>
        <li>
          Under the task&apos;s Environment Variables, add <Mono>ZEROSTRIKE_TOKEN</Mono> ={" "}
          <Mono>$(ZEROSTRIKE_TOKEN)</Mono>. Secret variables are not exposed to scripts unless mapped here.
        </li>
        <li>
          Place the task after checkout and build, and before any deploy or release stage, so a failing gate
          stops the release.
        </li>
        <li>
          Set the agent pool to <Mono>Azure Pipelines</Mono> with image <Mono>ubuntu-latest</Mono>. A
          self-hosted agent needs <Mono>curl</Mono>, <Mono>jq</Mono> and <Mono>sha256sum</Mono>.
        </li>
      </ol>

      <CopyBlock label="Bash task script" text={script} filename="thinkshield-scan.sh" />

      <div className="space-y-2 text-xs text-muted-foreground">
        <p>
          <strong className="text-foreground">Platform:</strong> Windows and PowerShell agents are not
          supported yet; this phase covers Linux (amd64) agents only.
        </p>
        <p>
          <strong className="text-foreground">Branches and PRs:</strong> to scan pull requests, add a branch
          policy build validation that runs this pipeline. A PR run records the source branch.
        </p>
        <p>
          <strong className="text-foreground">Exit behaviour:</strong> 0 and 1 (findings found) pass; 2 is a
          real failure (bad token, download or upload error). When findings trip{" "}
          <Mono>ZEROSTRIKE_FAIL_ON</Mono> the task exits 1. For warn-only, set <Mono>ZEROSTRIKE_FAIL_ON</Mono>{" "}
          to <Mono>none</Mono> or enable &quot;Continue on error&quot; on the task.{" "}
          {FAIL_ON_OPTIONS.find((o) => o.value === failOn)?.description} Change this in{" "}
          <Link href={`/projects/${projectId}?tab=settings`} className="underline underline-offset-2">
            Project Settings
          </Link>
          .
        </p>
        <p>
          <strong className="text-foreground">Report:</strong> optionally add a Publish build artifacts task for{" "}
          <Mono>$(Agent.TempDirectory)/zerostrike/zerostrike-report.json</Mono> to keep the JSON report.
        </p>
        <p>
          More detail in the{" "}
          <Link href="/guide#azure-devops-classic" className="underline underline-offset-2">
            Azure DevOps Classic guide
          </Link>
          .
        </p>
      </div>
    </div>
  );
}

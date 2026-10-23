import type { FailOn } from "@/lib/cicd-fail-on";

/** "https://portal/", "https://portal/api/v1/" -> "https://portal". */
export function normalizeOrigin(origin: string): string {
  return origin.replace(/\/+$/, "").replace(/\/api\/v1$/, "").replace(/\/+$/, "");
}

export type AgentOs = "linux" | "windows";

/** The full scan script, served by the backend (backend/app/ci_scripts/azure-classic.{sh,ps1}). */
export function azureClassicScriptUrl(origin: string, os: AgentOs = "linux"): string {
  return `${normalizeOrigin(origin)}/api/v1/downloads/ci/azure-classic.${os === "windows" ? "ps1" : "sh"}`;
}

/**
 * Inline script for a Classic PowerShell task on a Windows agent: the same download-and-run as the
 * Bash one. The hosted script runs in a child of the same engine (Windows PowerShell 5.1 or pwsh,
 * whichever the task uses) with -ExecutionPolicy Bypass, so a restrictive agent policy cannot block
 * the downloaded file. Exit code passes through. The test suite runs a copy of this exactly as the
 * task does.
 */
export function azureClassicPowerShellInlineScript(opts: { origin: string; failOn: FailOn }): string {
  return [
    "$ErrorActionPreference = 'Stop'",
    `if (-not $env:ZEROSTRIKE_PORTAL_URL) { $env:ZEROSTRIKE_PORTAL_URL = '${normalizeOrigin(opts.origin)}' }`,
    `if (-not $env:ZEROSTRIKE_FAIL_ON) { $env:ZEROSTRIKE_FAIL_ON = '${opts.failOn}' }`,
    "[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12",
    "$s = Join-Path $env:AGENT_TEMPDIRECTORY 'thinkshield-scan.ps1'",
    'Invoke-WebRequest -UseBasicParsing "$env:ZEROSTRIKE_PORTAL_URL/api/v1/downloads/ci/azure-classic.ps1" -OutFile $s',
    "& (Get-Process -Id $PID).Path -NoProfile -ExecutionPolicy Bypass -File $s",
    "exit $LASTEXITCODE",
  ].join("\n");
}

/**
 * Inline script for an Azure DevOps Classic Bash task. The inline field is capped at 5000
 * characters, so it only downloads the portal-hosted script and runs it. Pipeline variables
 * ZEROSTRIKE_PORTAL_URL / ZEROSTRIKE_FAIL_ON / ZEROSTRIKE_VERSION override the defaults baked in here;
 * the token comes from the ZEROSTRIKE_TOKEN env var the user maps in the task, never this text.
 * backend/tests/test_azure_classic_script.py runs a copy of this exactly as the task does.
 */
export function azureClassicInlineScript(opts: { origin: string; failOn: FailOn }): string {
  return [
    "set -e",
    `export ZEROSTRIKE_PORTAL_URL="\${ZEROSTRIKE_PORTAL_URL:-${normalizeOrigin(opts.origin)}}"`,
    `export ZEROSTRIKE_FAIL_ON="\${ZEROSTRIKE_FAIL_ON:-${opts.failOn}}"`,
    'curl -fsSL "$ZEROSTRIKE_PORTAL_URL/api/v1/downloads/ci/azure-classic.sh" -o "$AGENT_TEMPDIRECTORY/thinkshield-scan.sh"',
    'bash "$AGENT_TEMPDIRECTORY/thinkshield-scan.sh"',
  ].join("\n");
}

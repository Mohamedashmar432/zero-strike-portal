import type { FailOn } from "@/lib/cicd-fail-on";

/** "https://portal/", "https://portal/api/v1/" -> "https://portal". */
export function normalizeOrigin(origin: string): string {
  return origin.replace(/\/+$/, "").replace(/\/api\/v1$/, "").replace(/\/+$/, "");
}

/** The full scan script, served by the backend (backend/app/ci_scripts/azure-classic.sh). */
export function azureClassicScriptUrl(origin: string): string {
  return `${normalizeOrigin(origin)}/api/v1/downloads/ci/azure-classic.sh`;
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

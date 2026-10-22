import type { FailOn } from "@/lib/cicd-fail-on";
import { findingsGateLines } from "./findings-gate";

export const VERSION_PLACEHOLDER = "<ZEROSTRIKE_VERSION>";

/** "https://portal/", "https://portal/api/v1/" -> "https://portal". */
export function normalizeOrigin(origin: string): string {
  return origin.replace(/\/+$/, "").replace(/\/api\/v1$/, "").replace(/\/+$/, "");
}

/**
 * Inline Bash for an Azure DevOps Classic (designer) pipeline task on an Ubuntu agent. The scan
 * runs locally (no --server/--token); the script registers the scan, uploads the JSON report, and
 * gates on ZEROSTRIKE_FAIL_ON. The project token is read from the ZEROSTRIKE_TOKEN env var the user
 * maps in the task, and is only ever handed to curl on stdin (`--config -`), never argv or logs.
 */
export function azureClassicBashScript(opts: { origin: string; version: string | null; failOn: FailOn }): string {
  const origin = normalizeOrigin(opts.origin);
  const version = opts.version ?? VERSION_PLACEHOLDER;
  const report = '"$WORK/zerostrike-report.json"';
  const gate = findingsGateLines(report, ['echo "##vso[task.logissue type=error]$msg"'], [
    'echo "##vso[task.complete result=SucceededWithIssues;]thinkShield findings"',
  ]);
  return [
    "#!/usr/bin/env bash",
    "# thinkShield scan for an Azure DevOps Classic pipeline (Ubuntu agent, Bash task, Type: Inline).",
    `# Downloads ${origin}/api/v1/downloads/zerostrike/${version}/linux-amd64`,
    "set -euo pipefail",
    "",
    "# The project token must be mapped into this task: Environment Variables > ZEROSTRIKE_TOKEN = $(ZEROSTRIKE_TOKEN)",
    'if [ -z "${ZEROSTRIKE_TOKEN:-}" ]; then',
    '  echo "##vso[task.logissue type=error]ZEROSTRIKE_TOKEN is not set. Add it as a secret pipeline variable and map it in this task under Environment Variables."',
    "  exit 2",
    "fi",
    `PORTAL="\${ZEROSTRIKE_PORTAL_URL:-${origin}}"`,
    'PORTAL="${PORTAL%/}"; PORTAL="${PORTAL%/api/v1}"',
    `VERSION="\${ZEROSTRIKE_VERSION:-${version}}"`,
    `ZEROSTRIKE_FAIL_ON="\${ZEROSTRIKE_FAIL_ON:-${opts.failOn}}"`,
    "",
    'WORK="$AGENT_TEMPDIRECTORY/zerostrike"',
    'mkdir -p "$WORK"',
    'cd "$WORK"',
    "",
    "# The Authorization header goes to curl on stdin so the token never appears in argv or logs.",
    "auth() { printf 'header = \"Authorization: Bearer %s\"\\n' \"$ZEROSTRIKE_TOKEN\"; }",
    "mark_failed() {",
    '  auth | curl -sS --config - -X PUT -H "Content-Type: application/json" \\',
    '    --data \'{"status":"failed"}\' "$PORTAL/api/v1/scans/$1/status" >/dev/null 2>&1 || true',
    "}",
    "",
    "# 1. Download the scanner and verify it against the portal's checksums for the same version.",
    'BASE="$PORTAL/api/v1/downloads/zerostrike/$VERSION"',
    'if ! curl --fail --location -sS "$BASE/linux-amd64" -o zerostrike_linux_amd64; then',
    '  echo "##vso[task.logissue type=error]Could not download the thinkShield scanner from $BASE/linux-amd64. HTTP 404 means no Linux (amd64) binary is published for this version; a portal admin must publish it. Check ZEROSTRIKE_PORTAL_URL and ZEROSTRIKE_VERSION."',
    "  exit 2",
    "fi",
    'if ! curl --fail --location -sS "$BASE/checksums.txt" -o checksums.txt \\',
    '  || ! grep " zerostrike_linux_amd64$" checksums.txt | sha256sum -c -; then',
    '  echo "##vso[task.logissue type=error]Scanner checksum could not be fetched or did not match. Pin ZEROSTRIKE_VERSION to a published version."',
    "  exit 2",
    "fi",
    "chmod +x ./zerostrike_linux_amd64",
    "",
    "# 2. Register the scan with the portal.",
    'BRANCH="${SYSTEM_PULLREQUEST_SOURCEBRANCH:-${BUILD_SOURCEBRANCH:-}}"',
    'BRANCH="${BRANCH#refs/heads/}"',
    'BUILD_URL=""',
    'if [ -n "${SYSTEM_COLLECTIONURI:-}" ]; then',
    '  BUILD_URL="${SYSTEM_COLLECTIONURI%/}/${SYSTEM_TEAMPROJECTID:-}/_build/results?buildId=${BUILD_BUILDID:-}"',
    "fi",
    "body=$(jq -n \\",
    '  --arg git_commit "${BUILD_SOURCEVERSION:-}" \\',
    '  --arg branch "$BRANCH" \\',
    '  --arg repo_url "${BUILD_REPOSITORY_URI:-}" \\',
    '  --arg ci_build_id "${BUILD_BUILDID:-}" \\',
    '  --arg ci_build_number "${BUILD_BUILDNUMBER:-}" \\',
    '  --arg ci_build_url "$BUILD_URL" \\',
    '  --arg scan_label "ADO Classic: ${BUILD_DEFINITIONNAME:-pipeline} #${BUILD_BUILDNUMBER:-}" \\',
    '  --arg scanner_version "$VERSION" \\',
    "  '{triggered_by: \"ci\", ci_provider: \"azure_pipelines\", git_commit: $git_commit, branch: $branch,",
    "    repo_url: $repo_url, ci_build_id: $ci_build_id, ci_build_number: $ci_build_number,",
    "    ci_build_url: $ci_build_url, scan_label: $scan_label, scanner_version: $scanner_version}",
    "    | with_entries(select(.value != \"\"))')",
    "http=$(auth | curl -sS --config - -o register.json -w '%{http_code}' \\",
    '  -H "Content-Type: application/json" --data "$body" "$PORTAL/api/v1/scans" || true)',
    'if [ "$http" = "401" ]; then',
    '  echo "##vso[task.logissue type=error]thinkShield rejected the token: invalid, expired or revoked project API key."',
    "  exit 2",
    "fi",
    'case "$http" in 2??) ;; *)',
    '  echo "##vso[task.logissue type=error]Could not register the scan with the portal (HTTP $http)."',
    "  exit 2 ;;",
    "esac",
    "SCAN_ID=$(jq -r '.scan_id // empty' register.json)",
    'if [ -z "$SCAN_ID" ]; then',
    '  echo "##vso[task.logissue type=error]The portal did not return a scan id."',
    "  exit 2",
    "fi",
    "",
    "# 3. Scan the checked-out sources locally (nothing is sent until the upload below).",
    "rc=0",
    './zerostrike_linux_amd64 scan "$BUILD_SOURCESDIRECTORY" \\',
    "  --enable-secrets --enable-sca --enable-framework-checks \\",
    `  --format json --output ${report} || rc=$?`,
    "# 1 = findings were found (not an error); anything higher is a genuine failure.",
    'if [ "$rc" -gt 1 ]; then',
    '  echo "##vso[task.logissue type=error]thinkShield scan failed (exit code $rc)"',
    '  mark_failed "$SCAN_ID"',
    '  exit "$rc"',
    "fi",
    "",
    "# 4. Upload the report.",
    "http=$(auth | curl -sS --config - -o upload.json -w '%{http_code}' \\",
    `  -H "Content-Type: application/json" --data-binary @${report} \\`,
    '  "$PORTAL/api/v1/scans/$SCAN_ID/upload/json" || true)',
    'case "$http" in 2??) ;; *)',
    '  echo "##vso[task.logissue type=error]thinkShield scan ran locally but upload failed (HTTP $http)."',
    '  mark_failed "$SCAN_ID"',
    "  exit 2 ;;",
    "esac",
    'echo "thinkShield: report uploaded for scan $SCAN_ID"',
    "",
    "# 5. Gate on ZEROSTRIKE_FAIL_ON (none = warn only, critical, high).",
    ...gate,
  ].join("\n");
}

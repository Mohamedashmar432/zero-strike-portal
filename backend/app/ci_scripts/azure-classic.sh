#!/usr/bin/env bash
# thinkShield scan for an Azure DevOps Classic pipeline (Ubuntu agent).
#
# Served by the portal at /api/v1/downloads/ci/azure-classic.sh so the Bash task's inline script
# (capped at 5000 characters by Azure DevOps) only has to download and run it. Inputs, all env vars:
#   ZEROSTRIKE_TOKEN       project API key (secret; map it in the task's Environment Variables)
#   ZEROSTRIKE_PORTAL_URL  portal origin, e.g. https://portal.example.com
#   ZEROSTRIKE_VERSION     scanner version, default "latest" (resolved to a concrete version below)
#   ZEROSTRIKE_FAIL_ON     none | critical | high (default high)
# Exit codes: 0 pass, 1 findings tripped ZEROSTRIKE_FAIL_ON, 2 setup/upload failure.
set -euo pipefail

err() { echo "##vso[task.logissue type=error]$1"; }

if [ -z "${ZEROSTRIKE_TOKEN:-}" ]; then
  err "ZEROSTRIKE_TOKEN is not set. Add it as a secret pipeline variable and map it in this task under Environment Variables."
  exit 2
fi
if [ -z "${ZEROSTRIKE_PORTAL_URL:-}" ]; then
  err "ZEROSTRIKE_PORTAL_URL is not set."
  exit 2
fi
for tool in curl jq sha256sum; do
  command -v "$tool" >/dev/null || { err "$tool is required on the agent."; exit 2; }
done
PORTAL="${ZEROSTRIKE_PORTAL_URL%/}"; PORTAL="${PORTAL%/api/v1}"
REQUESTED="${ZEROSTRIKE_VERSION:-latest}"
ZEROSTRIKE_FAIL_ON="${ZEROSTRIKE_FAIL_ON:-high}"

WORK="${AGENT_TEMPDIRECTORY:-${TMPDIR:-/tmp}}/zerostrike"
mkdir -p "$WORK"
cd "$WORK"
REPORT="$WORK/zerostrike-report.json"

# The Authorization header goes to curl on stdin so the token never appears in argv or logs.
auth() { printf 'header = "Authorization: Bearer %s"\n' "$ZEROSTRIKE_TOKEN"; }
mark_failed() {
  auth | curl -sS --config - -X PUT -H "Content-Type: application/json" \
    --data '{"status":"failed"}' "$PORTAL/api/v1/scans/$1/status" >/dev/null 2>&1 || true
}

# 1. Resolve the version once ("latest" -> e.g. v0.41.0), so the binary and its checksum come from
#    the same release even if a new one is published mid-run.
if ! VERSION=$(curl --fail --location -sS "$PORTAL/api/v1/downloads/zerostrike/$REQUESTED/linux-amd64/info" | jq -er .version); then
  err "No Linux (amd64) thinkShield scanner is published for version '$REQUESTED' at $PORTAL. A portal admin must publish it; check ZEROSTRIKE_PORTAL_URL and ZEROSTRIKE_VERSION."
  exit 2
fi
echo "thinkShield: scanner $VERSION (requested $REQUESTED), gate ZEROSTRIKE_FAIL_ON=$ZEROSTRIKE_FAIL_ON"
BASE="$PORTAL/api/v1/downloads/zerostrike/$VERSION"
if ! curl --fail --location -sS "$BASE/linux-amd64" -o zerostrike_linux_amd64; then
  err "Could not download the thinkShield scanner from $BASE/linux-amd64."
  exit 2
fi
if ! curl --fail --location -sS "$BASE/checksums.txt" -o checksums.txt \
  || ! grep " zerostrike_linux_amd64$" checksums.txt | sha256sum -c -; then
  err "Scanner checksum could not be fetched or did not match."
  exit 2
fi
chmod +x ./zerostrike_linux_amd64

# 2. Register the scan with the portal.
BRANCH="${SYSTEM_PULLREQUEST_SOURCEBRANCH:-${BUILD_SOURCEBRANCH:-}}"
BRANCH="${BRANCH#refs/heads/}"
BUILD_URL=""
if [ -n "${SYSTEM_COLLECTIONURI:-}" ]; then
  BUILD_URL="${SYSTEM_COLLECTIONURI%/}/${SYSTEM_TEAMPROJECTID:-}/_build/results?buildId=${BUILD_BUILDID:-}"
fi
body=$(jq -n \
  --arg git_commit "${BUILD_SOURCEVERSION:-}" \
  --arg branch "$BRANCH" \
  --arg repo_url "${BUILD_REPOSITORY_URI:-}" \
  --arg ci_build_id "${BUILD_BUILDID:-}" \
  --arg ci_build_number "${BUILD_BUILDNUMBER:-}" \
  --arg ci_build_url "$BUILD_URL" \
  --arg scan_label "ADO Classic: ${BUILD_DEFINITIONNAME:-pipeline} #${BUILD_BUILDNUMBER:-}" \
  --arg scanner_version "$VERSION" \
  '{triggered_by: "ci", ci_provider: "azure_pipelines", git_commit: $git_commit, branch: $branch,
    repo_url: $repo_url, ci_build_id: $ci_build_id, ci_build_number: $ci_build_number,
    ci_build_url: $ci_build_url, scan_label: $scan_label, scanner_version: $scanner_version}
    | with_entries(select(.value != ""))')
http=$(auth | curl -sS --config - -o register.json -w '%{http_code}' \
  -H "Content-Type: application/json" --data "$body" "$PORTAL/api/v1/scans" || true)
if [ "$http" = "401" ]; then
  err "thinkShield rejected the token: invalid, expired or revoked project API key."
  exit 2
fi
case "$http" in 2??) ;; *)
  err "Could not register the scan with the portal (HTTP $http)."
  exit 2 ;;
esac
SCAN_ID=$(jq -r '.scan_id // empty' register.json)
if [ -z "$SCAN_ID" ]; then
  err "The portal did not return a scan id."
  exit 2
fi

# 3. Scan the checked-out sources locally (nothing is sent until the upload below).
rc=0
./zerostrike_linux_amd64 scan "${BUILD_SOURCESDIRECTORY:-$OLDPWD}" \
  --enable-secrets --enable-sca --enable-framework-checks \
  --format json --output "$REPORT" || rc=$?
# 1 = findings were found (not an error); anything higher is a genuine failure.
if [ "$rc" -gt 1 ]; then
  err "thinkShield scan failed (exit code $rc)"
  mark_failed "$SCAN_ID"
  exit "$rc"
fi

# 4. Upload the report.
http=$(auth | curl -sS --config - -o upload.json -w '%{http_code}' \
  -H "Content-Type: application/json" --data-binary @"$REPORT" \
  "$PORTAL/api/v1/scans/$SCAN_ID/upload/json" || true)
case "$http" in 2??) ;; *)
  err "thinkShield scan ran locally but upload failed (HTTP $http)."
  mark_failed "$SCAN_ID"
  exit 2 ;;
esac
echo "thinkShield: report uploaded for scan $SCAN_ID"

# 5. Gate on ZEROSTRIKE_FAIL_ON. Same logic as the YAML snippets (frontend/lib/cicd/findings-gate.ts):
#    one "Severity" line per finding at this indent, so nested fields are not counted.
crit=$(grep -c '^      "Severity": "critical"' "$REPORT" || true)
high=$(grep -c '^      "Severity": "high"' "$REPORT" || true)
crit=${crit:-0}
high=${high:-0}
if [ "$crit" -gt 0 ] || [ "$high" -gt 0 ]; then
  err "thinkShield: $crit critical and $high high severity findings. See the thinkShield portal."
  case "$ZEROSTRIKE_FAIL_ON" in
    critical) blocking=$crit ;;
    high) blocking=$((crit + high)) ;;
    *) blocking=0 ;;
  esac
  if [ "$blocking" -gt 0 ]; then
    echo "thinkShield: failing the pipeline (ZEROSTRIKE_FAIL_ON=$ZEROSTRIKE_FAIL_ON, $blocking blocking)"
    exit 1
  fi
  echo "##vso[task.complete result=SucceededWithIssues;]thinkShield findings"
fi

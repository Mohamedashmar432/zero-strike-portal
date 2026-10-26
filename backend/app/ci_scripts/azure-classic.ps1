# thinkShield scan for an Azure DevOps Classic pipeline (Windows agent, PowerShell task).
#
# Served by the portal at /api/v1/downloads/ci/azure-classic.ps1; the task's inline script only
# downloads and runs it. The Windows twin of azure-classic.sh: same inputs, steps and exit codes.
# Runs on Windows PowerShell 5.1 and PowerShell 7 with built-in cmdlets only (no curl/jq/Git Bash),
# so any Windows agent works: hosted windows-2022/windows-latest or self-hosted Server 2016+.
# Keep this file ASCII: Windows PowerShell 5.1 reads a BOM-less script as ANSI.
#   ZEROSTRIKE_TOKEN       project API key (secret; map it in the task's Environment Variables)
#   ZEROSTRIKE_PORTAL_URL  portal origin, e.g. https://portal.example.com
#   ZEROSTRIKE_VERSION     scanner version, default "latest" (resolved to a concrete version below)
#   ZEROSTRIKE_FAIL_ON     none | critical | high (default high)
# Exit codes: 0 pass, 1 findings tripped ZEROSTRIKE_FAIL_ON, 2 setup/upload failure.
[Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidUsingWriteHost', '',
  Justification = 'Azure DevOps reads ##vso logging commands from the host output; Write-Host is the documented way.')]
param()
$ErrorActionPreference = 'Stop'
# Windows PowerShell 5.1 redraws a progress bar per chunk, which makes downloads ~10x slower.
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

function Write-TaskError([string]$Message) { Write-Host "##vso[task.logissue type=error]$Message" }
function Exit-Task([string]$Message, [int]$Code = 2) { Write-TaskError $Message; exit $Code }
# HTTP status of a failed web call, on both 5.1 (WebException) and 7 (HttpResponseException).
function Get-HttpStatus($ErrorRecord) {
  if ($ErrorRecord.Exception.Response) { return [int]$ErrorRecord.Exception.Response.StatusCode }
  return 0
}

if (-not $env:ZEROSTRIKE_TOKEN) {
  Exit-Task 'ZEROSTRIKE_TOKEN is not set. Add it as a secret pipeline variable and map it in this task under Environment Variables.'
}
if (-not $env:ZEROSTRIKE_PORTAL_URL) { Exit-Task 'ZEROSTRIKE_PORTAL_URL is not set.' }
$portal = $env:ZEROSTRIKE_PORTAL_URL.TrimEnd('/')
if ($portal.EndsWith('/api/v1')) { $portal = $portal.Substring(0, $portal.Length - 7) }
$requested = if ($env:ZEROSTRIKE_VERSION) { $env:ZEROSTRIKE_VERSION } else { 'latest' }
$failOn = if ($env:ZEROSTRIKE_FAIL_ON) { $env:ZEROSTRIKE_FAIL_ON } else { 'high' }

$tempRoot = if ($env:AGENT_TEMPDIRECTORY) { $env:AGENT_TEMPDIRECTORY } else { [IO.Path]::GetTempPath() }
$work = Join-Path $tempRoot 'zerostrike'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$exe = Join-Path $work 'zerostrike_windows_amd64.exe'
$report = Join-Path $work 'zerostrike-report.json'
# The token only ever travels in a header of an in-process web call: never argv, never logs.
$auth = @{ Authorization = "Bearer $env:ZEROSTRIKE_TOKEN" }

function Send-ScanFailed([string]$Id) {
  try {
    Invoke-RestMethod -Method Put -Uri "$portal/api/v1/scans/$Id/status" -Headers $auth `
      -ContentType 'application/json' -Body '{"status":"failed"}' | Out-Null
  } catch {
    # Best effort: the task is already failing with the real reason; this only tidies the portal.
    Write-Host "thinkShield: could not mark scan $Id failed ($($_.Exception.Message))"
  }
}

# 1. Resolve the version once ("latest" -> e.g. v0.41.0), so the binary and its checksum come from
#    the same release even if a new one is published mid-run. Failure messages carry the underlying
#    error (DNS, TLS, proxy, 404) because on a self-hosted agent that is usually the whole story.
$version = $null
try { $version = (Invoke-RestMethod -Uri "$portal/api/v1/downloads/zerostrike/$requested/windows-amd64/info").version }
catch { $why = $_.Exception.Message }
if (-not $version) {
  Exit-Task "No Windows (amd64) thinkShield scanner is published for version '$requested' at $portal ($why). A portal admin must publish it; check ZEROSTRIKE_PORTAL_URL and ZEROSTRIKE_VERSION."
}
Write-Host "thinkShield: scanner $version (requested $requested), gate ZEROSTRIKE_FAIL_ON=$failOn"
$base = "$portal/api/v1/downloads/zerostrike/$version"
try { Invoke-WebRequest -UseBasicParsing -Uri "$base/windows-amd64" -OutFile $exe }
catch { Exit-Task "Could not download the thinkShield scanner from $base/windows-amd64 ($($_.Exception.Message))." }
$expected = $null
$why = 'no entry for zerostrike_windows_amd64.exe'
try {
  # Via a file: 5.1 hands .Content back as a byte[] whenever the response is not typed as text.
  $sumsFile = Join-Path $work 'checksums.txt'
  Invoke-WebRequest -UseBasicParsing -Uri "$base/checksums.txt" -OutFile $sumsFile
  $line = Get-Content -LiteralPath $sumsFile | Where-Object { $_ -match '\s\*?zerostrike_windows_amd64\.exe\s*$' } | Select-Object -First 1
  if ($line) { $expected = ($line.Trim() -split '\s+')[0].ToLowerInvariant() }
} catch { $why = $_.Exception.Message }
$actual = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if (-not $expected) { Exit-Task "Scanner checksum could not be fetched ($why)." }
if ($expected -ne $actual) { Exit-Task 'Scanner checksum did not match the published one.' }

# 2. Register the scan with the portal.
$branch = if ($env:SYSTEM_PULLREQUEST_SOURCEBRANCH) { $env:SYSTEM_PULLREQUEST_SOURCEBRANCH } else { [string]$env:BUILD_SOURCEBRANCH }
$branch = $branch -replace '^refs/heads/', ''
$buildUrl = ''
if ($env:SYSTEM_COLLECTIONURI) {
  $buildUrl = "$($env:SYSTEM_COLLECTIONURI.TrimEnd('/'))/$env:SYSTEM_TEAMPROJECTID/_build/results?buildId=$env:BUILD_BUILDID"
}
$fields = [ordered]@{
  triggered_by    = 'ci'
  ci_provider     = 'azure_pipelines'
  git_commit      = [string]$env:BUILD_SOURCEVERSION
  branch          = $branch
  repo_url        = [string]$env:BUILD_REPOSITORY_URI
  ci_build_id     = [string]$env:BUILD_BUILDID
  ci_build_number = [string]$env:BUILD_BUILDNUMBER
  ci_build_url    = $buildUrl
  scan_label      = "ADO Classic: $(if ($env:BUILD_DEFINITIONNAME) { $env:BUILD_DEFINITIONNAME } else { 'pipeline' }) #$env:BUILD_BUILDNUMBER"
  scanner_version = $version
}
$body = [ordered]@{}
foreach ($k in $fields.Keys) { if ($fields[$k]) { $body[$k] = $fields[$k] } }
# Send UTF-8 bytes: 5.1 would otherwise encode a string body as ISO-8859-1 (branch names can be non-ASCII).
$bodyBytes = [Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Compress))
try {
  $registered = Invoke-RestMethod -Method Post -Uri "$portal/api/v1/scans" -Headers $auth `
    -ContentType 'application/json; charset=utf-8' -Body $bodyBytes
} catch {
  $status = Get-HttpStatus $_
  if ($status -eq 401) { Exit-Task 'thinkShield rejected the token: invalid, expired or revoked project API key.' }
  Exit-Task "Could not register the scan with the portal (HTTP $status)."
}
$scanId = [string]$registered.scan_id
if (-not $scanId) { Exit-Task 'The portal did not return a scan id.' }
# Findings a portal admin accepted (false positive / accepted dependency risk): the scanner still
# reports them but leaves them out of the counts the gate below reads. An older scanner ignores this.
# -InputObject keeps a one-item list an array, and the BOM-less encoding matters: 5.1's UTF-8 writes
# a BOM, which the scanner's JSON reader rejects.
$exemptions = @($registered.accepted_exemptions | Where-Object { $_ })
$exemptionsFile = Join-Path $work 'exemptions.json'
[IO.File]::WriteAllText($exemptionsFile, (ConvertTo-Json -InputObject $exemptions -Depth 4 -Compress),
  (New-Object Text.UTF8Encoding $false))
$env:ZEROSTRIKE_ACCEPTED_EXEMPTIONS_FILE = $exemptionsFile

# 3. Scan the checked-out sources locally (nothing is sent until the upload below). 'Continue' so a
#    line on the scanner's stderr is not turned into a terminating error by Windows PowerShell 5.1.
$sources = if ($env:BUILD_SOURCESDIRECTORY) { $env:BUILD_SOURCESDIRECTORY } else { (Get-Location).Path }
$ErrorActionPreference = 'Continue'
& $exe scan $sources --enable-secrets --enable-sca --enable-framework-checks --format json --output $report
$rc = $LASTEXITCODE
$ErrorActionPreference = 'Stop'
# 1 = findings were found (not an error); anything higher is a genuine failure.
if ($rc -gt 1 -or -not (Test-Path -LiteralPath $report)) {
  Write-TaskError "thinkShield scan failed (exit code $rc)"
  Send-ScanFailed $scanId
  exit $(if ($rc -gt 1) { $rc } else { 2 })
}

# 4. Upload the report.
try {
  Invoke-RestMethod -Method Post -Uri "$portal/api/v1/scans/$scanId/upload/json" -Headers $auth `
    -ContentType 'application/json' -InFile $report | Out-Null
} catch {
  Write-TaskError "thinkShield scan ran locally but upload failed (HTTP $(Get-HttpStatus $_))."
  Send-ScanFailed $scanId
  exit 2
}
Write-Host "thinkShield: report uploaded for scan $scanId"

# 5. Gate on ZEROSTRIKE_FAIL_ON. Same rule as the Linux script and the YAML snippets: one "Severity"
#    line per finding at this indent, so nested fields are not counted.
$lines = Get-Content -LiteralPath $report
$crit = @($lines | Where-Object { $_ -cmatch '^      "Severity": "critical"' }).Count
$high = @($lines | Where-Object { $_ -cmatch '^      "Severity": "high"' }).Count
if ($crit -gt 0 -or $high -gt 0) {
  Write-TaskError "thinkShield: $crit critical and $high high severity findings. See the thinkShield portal."
  $blocking = switch ($failOn) { 'critical' { $crit } 'high' { $crit + $high } default { 0 } }
  if ($blocking -gt 0) {
    Write-Host "thinkShield: failing the pipeline (ZEROSTRIKE_FAIL_ON=$failOn, $blocking blocking)"
    exit 1
  }
  Write-Host '##vso[task.complete result=SucceededWithIssues;]thinkShield findings'
}
# Explicit: the scanner's exit code 1 (findings) must not leak out as the task's result.
exit 0

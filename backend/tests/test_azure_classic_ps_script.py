"""Runs the hosted Windows Classic script the way the PowerShell@2 task does: the inline field is
written to a .ps1 and dot-sourced by `powershell.exe -NoProfile -NonInteractive -ExecutionPolicy
Unrestricted -Command`, with the agent's predefined variables as env vars. Runs under every engine
found (Windows PowerShell 5.1 and pwsh 7). A stub portal stands in for the backend and a tiny Go
program for the scanner .exe, so the whole download -> verify -> register -> scan -> upload -> gate
path runs on any Windows machine.

Exit codes: Windows PowerShell 5.1 reports any non-zero `exit` from a script dot-sourced under -Command
as 1, and that is how the task runs inline scripts. So on Windows the task fails either way and the
reason is in the ##vso error line; failure cases assert non-zero plus that line, not 1 vs 2."""

import json
import os
import shutil
import subprocess

import pytest

from tests.test_azure_classic_script import TOKEN, VULN_PY, _portal

ENGINES = [e for e in (shutil.which("powershell.exe") and "powershell.exe", shutil.which("pwsh") and "pwsh") if e]
GO = shutil.which("go")
pytestmark = pytest.mark.skipif(os.name != "nt" or not ENGINES or not GO, reason="needs Windows, PowerShell and Go")

# Mirrors frontend/lib/cicd/azure-classic.ts: azureClassicPowerShellInlineScript().
INLINE_PS = """$ErrorActionPreference = 'Stop'
if (-not $env:ZEROSTRIKE_PORTAL_URL) {{ $env:ZEROSTRIKE_PORTAL_URL = '{origin}' }}
if (-not $env:ZEROSTRIKE_FAIL_ON) {{ $env:ZEROSTRIKE_FAIL_ON = '{fail_on}' }}
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$s = Join-Path $env:AGENT_TEMPDIRECTORY 'thinkshield-scan.ps1'
Invoke-WebRequest -UseBasicParsing "$env:ZEROSTRIKE_PORTAL_URL/api/v1/downloads/ci/azure-classic.ps1" -OutFile $s
& (Get-Process -Id $PID).Path -NoProfile -ExecutionPolicy Bypass -File $s
exit $LASTEXITCODE
"""

# Writes a report with STUB_SEVERITIES (comma-separated) to --output, prints a line on stderr (Windows
# PowerShell 5.1 can turn native stderr into a terminating error), exits 1 when it found something.
STUB_SCANNER_GO = r"""package main

import (
	"fmt"
	"os"
	"strings"
)

func main() {
	out := ""
	for i, a := range os.Args {
		if a == "--output" && i+1 < len(os.Args) {
			out = os.Args[i+1]
		}
	}
	var parts []string
	if s := os.Getenv("STUB_SEVERITIES"); s != "" {
		for _, sev := range strings.Split(s, ",") {
			parts = append(parts, fmt.Sprintf("    {\n      \"Severity\": %q\n    }", sev))
		}
	}
	os.WriteFile(out, []byte("{\n  \"Findings\": [\n"+strings.Join(parts, ",\n")+"\n  ]\n}\n"), 0o644)
	fmt.Fprintln(os.Stderr, "stub scanner: progress on stderr")
	if len(parts) > 0 {
		os.Exit(1)
	}
}
"""


@pytest.fixture(scope="module")
def stub_exe(tmp_path_factory) -> bytes:
    d = tmp_path_factory.mktemp("stubscanner")
    (d / "main.go").write_text(STUB_SCANNER_GO)
    subprocess.run([GO, "build", "-o", str(d / "stub.exe"), str(d / "main.go")], check=True, cwd=d,
                   env={**os.environ, "GO111MODULE": "off", "CGO_ENABLED": "0"}, timeout=300)
    return (d / "stub.exe").read_bytes()


@pytest.fixture(params=ENGINES)
def engine(request):
    return request.param


def _run(client, tmp_path, engine, binary, severities=(), fail_on="high", token=TOKEN, extra_env=None,
         bad_sha=False, origin=None, sources_files=None):
    script = client.get("/api/v1/downloads/ci/azure-classic.ps1").text
    calls: list = []
    server = _portal(script, binary, calls, bad_sha, platform="windows-amd64", script_name="azure-classic.ps1")
    origin = origin or f"http://127.0.0.1:{server.server_port}"
    try:
        agent_tmp, sources = tmp_path / "agent_tmp", tmp_path / "s"
        agent_tmp.mkdir()
        sources.mkdir()
        for name, text in (sources_files or {}).items():
            (sources / name).write_text(text)
        task = tmp_path / "task.ps1"
        task.write_text(INLINE_PS.format(origin=origin, fail_on=fail_on))
        env = {
            **os.environ,
            "STUB_SEVERITIES": ",".join(severities),
            "ZEROSTRIKE_TOKEN": token,
            "AGENT_TEMPDIRECTORY": str(agent_tmp),
            "BUILD_SOURCESDIRECTORY": str(sources),
            "BUILD_SOURCEBRANCH": "refs/heads/main",
            "BUILD_SOURCEVERSION": "abc123",
            "BUILD_BUILDID": "42",
            "BUILD_BUILDNUMBER": "20261023.1",
            "BUILD_DEFINITIONNAME": "dotnet-ci",
            "SYSTEM_COLLECTIONURI": "https://dev.azure.com/org/",
            "SYSTEM_TEAMPROJECTID": "proj",
            **(extra_env or {}),
        }
        for k in ("ZEROSTRIKE_FAIL_ON", "ZEROSTRIKE_PORTAL_URL", "ZEROSTRIKE_VERSION"):
            if k not in (extra_env or {}):
                env.pop(k, None)
        # How the PowerShell@2 task launches an inline script.
        cmd = [engine, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Unrestricted",
               "-Command", f". '{task}'"]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=180)
    finally:
        server.shutdown()
    return proc, calls


def test_ps_script_is_served_and_ascii(client):
    r = client.get("/api/v1/downloads/ci/azure-classic.ps1")
    assert r.status_code == 200
    assert r.text.isascii()  # Windows PowerShell 5.1 reads a BOM-less script as ANSI


def test_clean_scan_registers_uploads_and_passes(client, tmp_path, engine, stub_exe):
    proc, calls = _run(client, tmp_path, engine, stub_exe)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    register = next(json.loads(b) for m, p, b in calls if m == "POST" and p == "/api/v1/scans")
    assert register["ci_provider"] == "azure_pipelines"
    assert register["branch"] == "main"
    assert register["scanner_version"] == "v9.9.9"
    assert register["ci_build_url"] == "https://dev.azure.com/org/proj/_build/results?buildId=42"
    assert register["scan_label"] == "ADO Classic: dotnet-ci #20261023.1"
    assert ("POST", "/api/v1/scans/scan123/upload/json") in [(m, p) for m, p, _ in calls]
    assert TOKEN not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "severities, fail_on, code, marker",
    [
        (["high"], "high", "fail", "failing the pipeline"),
        (["high"], "critical", 0, "SucceededWithIssues"),
        (["critical"], "critical", "fail", "failing the pipeline"),
        (["critical", "high"], "none", 0, "SucceededWithIssues"),
        (["medium"], "high", 0, "report uploaded"),
    ],
)
def test_gate(client, tmp_path, engine, stub_exe, severities, fail_on, code, marker):
    proc, _ = _run(client, tmp_path, engine, stub_exe, severities, fail_on=fail_on)
    assert (proc.returncode != 0 if code == "fail" else proc.returncode == code), proc.stdout + proc.stderr
    assert marker in proc.stdout


def test_pipeline_variable_overrides_the_snippet_default(client, tmp_path, engine, stub_exe):
    proc, _ = _run(client, tmp_path, engine, stub_exe, ["high"], extra_env={"ZEROSTRIKE_FAIL_ON": "none"})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bad_token_fails(client, tmp_path, engine, stub_exe):
    proc, _ = _run(client, tmp_path, engine, stub_exe, token="wrong")
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "rejected the token" in proc.stdout


def test_missing_token_fails_before_any_download(client, tmp_path, engine, stub_exe):
    proc, calls = _run(client, tmp_path, engine, stub_exe, token="")
    assert proc.returncode != 0
    assert "ZEROSTRIKE_TOKEN is not set" in proc.stdout
    assert [p for _, p, _ in calls] == ["/api/v1/downloads/ci/azure-classic.ps1"]


def test_checksum_mismatch_fails(client, tmp_path, engine, stub_exe):
    proc, calls = _run(client, tmp_path, engine, stub_exe, bad_sha=True)
    assert proc.returncode != 0, proc.stdout + proc.stderr
    assert "checksum" in proc.stdout
    assert not any(p == "/api/v1/scans" for _, p, _ in calls)


def test_unreachable_portal_fails_the_task_at_the_download(client, tmp_path, engine, stub_exe):
    proc, _ = _run(client, tmp_path, engine, stub_exe, origin="http://127.0.0.1:9")
    assert proc.returncode != 0


# Set by the Windows CI job to a real CGO build of the scanner (windows-amd64).
REAL_SCANNER = os.environ.get("ZEROSTRIKE_REAL_SCANNER_WINDOWS")


@pytest.mark.skipif(not REAL_SCANNER, reason="ZEROSTRIKE_REAL_SCANNER_WINDOWS not set")
def test_real_scanner_report_matches_the_gate(client, tmp_path, engine):
    with open(REAL_SCANNER, "rb") as f:
        binary = f.read()
    proc, calls = _run(client, tmp_path, engine, binary, fail_on="none", sources_files={"vuln.py": VULN_PY})
    print(proc.stdout)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(next(b for m, p, b in calls if p == "/api/v1/scans/scan123/upload/json"))
    findings = [f for v in report.values() if isinstance(v, list) for f in v if isinstance(f, dict) and "Severity" in f]
    assert findings, "real scanner found nothing in the vulnerable fixture (CGO build?)"
    crit = sum(f["Severity"] == "critical" for f in findings)
    high = sum(f["Severity"] == "high" for f in findings)
    if crit or high:
        assert f"{crit} critical and {high} high severity findings" in proc.stdout

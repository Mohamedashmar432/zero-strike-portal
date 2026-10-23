"""Runs the hosted Azure DevOps Classic script the way the Bash task does: the inline field is written
to a file and run with `bash --noprofile --norc`, with the agent's predefined variables as env vars.
A stub portal stands in for the backend and a shell script stands in for the scanner binary, so the
whole download -> verify -> register -> scan -> upload -> gate path runs without a Linux agent."""

import hashlib
import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

BASH, JQ, CURL = shutil.which("bash"), shutil.which("jq"), shutil.which("curl")
pytestmark = pytest.mark.skipif(not (BASH and JQ and CURL), reason="needs bash, jq and curl on PATH")

TOKEN = "zs_test_token_value"

# Mirrors frontend/lib/cicd/azure-classic.ts: azureClassicInlineScript().
INLINE = """set -e
export ZEROSTRIKE_PORTAL_URL="${{ZEROSTRIKE_PORTAL_URL:-{origin}}}"
export ZEROSTRIKE_FAIL_ON="${{ZEROSTRIKE_FAIL_ON:-{fail_on}}}"
curl -fsSL "$ZEROSTRIKE_PORTAL_URL/api/v1/downloads/ci/azure-classic.sh" -o "$AGENT_TEMPDIRECTORY/thinkshield-scan.sh"
bash "$AGENT_TEMPDIRECTORY/thinkshield-scan.sh"
"""


def _fake_scanner(severities: list[str]) -> bytes:
    findings = ",\n".join(f'    {{\n      "Severity": "{s}"\n    }}' for s in severities)
    report = '{\n  "Findings": [\n' + findings + "\n  ]\n}\n"
    # Writes the report to the path after --output; exits 1 when there are findings, like the scanner.
    return (
        "#!/usr/bin/env bash\n"
        'while [ $# -gt 0 ]; do [ "$1" = --output ] && out=$2; shift; done\n'
        f"cat > \"$out\" <<'EOF'\n{report}EOF\n"
        f"exit {1 if severities else 0}\n"
    ).encode()


def _portal(script: str, binary: bytes, calls: list, bad_sha: bool = False):
    sha = "0" * 64 if bad_sha else hashlib.sha256(binary).hexdigest()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes | str = b""):
            self.send_response(code)
            self.end_headers()
            self.wfile.write(body.encode() if isinstance(body, str) else body)

        def do_GET(self):
            p = self.path
            calls.append(("GET", p, None))
            routes = {
                "/api/v1/downloads/ci/azure-classic.sh": script,
                "/api/v1/downloads/zerostrike/latest/linux-amd64/info": json.dumps({"version": "v9.9.9"}),
                "/api/v1/downloads/zerostrike/v9.9.9/linux-amd64": binary,
                "/api/v1/downloads/zerostrike/v9.9.9/checksums.txt": f"{sha}  zerostrike_linux_amd64\n",
            }
            self._send(200, routes[p]) if p in routes else self._send(404)

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"] or 0))
            calls.append(("POST", self.path, body))
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401)
            if self.path == "/api/v1/scans":
                return self._send(201, json.dumps({"scan_id": "scan123"}))
            self._send(200, "{}")

        def do_PUT(self):
            calls.append(("PUT", self.path, None))
            self._send(200, "{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _run(client, tmp_path, severities, fail_on="high", token=TOKEN, extra_env=None, scanner=None, bad_sha=False,
         origin=None, sources_files=None):
    script = client.get("/api/v1/downloads/ci/azure-classic.sh").text
    calls: list = []
    server = _portal(script, scanner or _fake_scanner(severities), calls, bad_sha)
    origin = origin or f"http://127.0.0.1:{server.server_port}"
    try:
        agent_tmp, sources = tmp_path / "agent_tmp", tmp_path / "s"
        agent_tmp.mkdir()
        sources.mkdir()
        for name, text in (sources_files or {}).items():
            (sources / name).write_text(text, newline="\n")
        task = tmp_path / "task.sh"
        task.write_text(INLINE.format(origin=origin, fail_on=fail_on), newline="\n")
        env = {
            **os.environ,
            "ZEROSTRIKE_TOKEN": token,
            "AGENT_TEMPDIRECTORY": str(agent_tmp),
            "BUILD_SOURCESDIRECTORY": str(sources),
            "BUILD_SOURCEBRANCH": "refs/heads/main",
            "BUILD_SOURCEVERSION": "abc123",
            "BUILD_BUILDID": "42",
            "BUILD_BUILDNUMBER": "20261023.1",
            "BUILD_DEFINITIONNAME": "web-ci",
            "SYSTEM_COLLECTIONURI": "https://dev.azure.com/org/",
            "SYSTEM_TEAMPROJECTID": "proj",
            **(extra_env or {}),
        }
        # Exactly how the Bash@3 task launches an inline script.
        proc = subprocess.run([BASH, "--noprofile", "--norc", str(task)], env=env, capture_output=True, text=True,
                              timeout=60)
    finally:
        server.shutdown()
    return proc, calls


def test_inline_snippet_fits_the_5000_char_limit():
    assert len(INLINE.format(origin="https://portal.example.com", fail_on="high")) < 5000


def test_script_is_served_without_carriage_returns(client):
    r = client.get("/api/v1/downloads/ci/azure-classic.sh")
    assert r.status_code == 200
    assert "\r" not in r.text and r.text.startswith("#!/usr/bin/env bash")


def test_clean_scan_registers_uploads_and_passes(client, tmp_path):
    proc, calls = _run(client, tmp_path, [])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    register = next(json.loads(b) for m, p, b in calls if m == "POST" and p == "/api/v1/scans")
    assert register["ci_provider"] == "azure_pipelines"
    assert register["branch"] == "main"
    assert register["scanner_version"] == "v9.9.9"  # "latest" resolved to the concrete release
    assert register["ci_build_url"] == "https://dev.azure.com/org/proj/_build/results?buildId=42"
    assert ("POST", "/api/v1/scans/scan123/upload/json") in [(m, p) for m, p, _ in calls]
    assert TOKEN not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "severities, fail_on, code, marker",
    [
        (["high"], "high", 1, "failing the pipeline"),
        (["high"], "critical", 0, "SucceededWithIssues"),
        (["critical"], "critical", 1, "failing the pipeline"),
        (["critical", "high"], "none", 0, "SucceededWithIssues"),
        (["medium"], "high", 0, "report uploaded"),
    ],
)
def test_gate(client, tmp_path, severities, fail_on, code, marker):
    proc, _ = _run(client, tmp_path, severities, fail_on=fail_on)
    assert proc.returncode == code, proc.stdout + proc.stderr
    assert marker in proc.stdout


def test_pipeline_variable_overrides_the_snippet_default(client, tmp_path):
    proc, _ = _run(client, tmp_path, ["high"], fail_on="high", extra_env={"ZEROSTRIKE_FAIL_ON": "none"})
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_bad_token_fails_with_exit_2(client, tmp_path):
    proc, _ = _run(client, tmp_path, [], token="wrong")
    assert proc.returncode == 2
    assert "rejected the token" in proc.stdout


def test_missing_token_fails_before_any_download(client, tmp_path):
    proc, calls = _run(client, tmp_path, [], token="")
    assert proc.returncode == 2
    assert "ZEROSTRIKE_TOKEN is not set" in proc.stdout
    assert [p for _, p, _ in calls] == ["/api/v1/downloads/ci/azure-classic.sh"]


def test_checksum_mismatch_fails_with_exit_2(client, tmp_path):
    proc, calls = _run(client, tmp_path, [], bad_sha=True)
    assert proc.returncode == 2
    assert "checksum" in proc.stdout
    assert not any(p == "/api/v1/scans" for _, p, _ in calls)


def test_unreachable_portal_fails_the_task_at_the_download(client, tmp_path):
    # set -e in the inline script: a failed download must not fall through to a passing task.
    proc, _ = _run(client, tmp_path, [], origin="http://127.0.0.1:9")
    assert proc.returncode != 0


# Set by the Linux CI job to a real CGO build of the scanner (linux-amd64), so the gate's grep is
# checked against the scanner's actual report layout, not the stub's.
REAL_SCANNER = os.environ.get("ZEROSTRIKE_REAL_SCANNER")
VULN_PY = "import os\nfrom flask import request\ndef handler():\n    cmd = request.args.get('cmd')\n    os.system(cmd)\n"


@pytest.mark.skipif(not REAL_SCANNER, reason="ZEROSTRIKE_REAL_SCANNER not set")
def test_real_scanner_report_matches_the_gate(client, tmp_path):
    with open(REAL_SCANNER, "rb") as f:
        binary = f.read()
    proc, calls = _run(client, tmp_path, [], fail_on="none", scanner=binary, sources_files={"vuln.py": VULN_PY})
    print(proc.stdout)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(next(b for m, p, b in calls if p == "/api/v1/scans/scan123/upload/json"))
    findings = [f for v in report.values() if isinstance(v, list) for f in v if isinstance(f, dict) and "Severity" in f]
    assert findings, "real scanner found nothing in the vulnerable fixture (CGO build?)"
    expected = sum(f["Severity"] in ("critical", "high") for f in findings)
    # The gate counts '      "Severity": ...' lines; the message proves how many it saw.
    crit = sum(f["Severity"] == "critical" for f in findings)
    high = sum(f["Severity"] == "high" for f in findings)
    if expected:
        assert f"{crit} critical and {high} high severity findings" in proc.stdout
    else:
        assert "severity findings" not in proc.stdout

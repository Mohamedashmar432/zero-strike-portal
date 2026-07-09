"""Server-side cloud scan execution.

For a scan_type="cloud" Scan: clone the repo into an ephemeral workdir, run the
baked-in Go scanner binary against it, ingest the report via the shared
report_ingestion_service, and delete the clone (crash-safe). Kicked off as a
FastAPI BackgroundTask from the JWT create-scan endpoint.

Static analysis only — the target code is never executed — but git clone and the
SCA scanner hit the network, so: SSRF guard on repo_url, per-step timeouts with
process-group kill, and guaranteed workdir cleanup.
"""

import asyncio
import ipaddress
import os
import shutil
import signal
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.models.scan import Scan
from app.schemas.report import GoReportIn
from app.services import report_ingestion_service
from app.storage import artifact_store

_semaphore: asyncio.Semaphore | None = None


class CloudScanError(Exception):
    """A recoverable cloud-scan failure; message is surfaced (sanitized) on the scan."""


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.max_concurrent_cloud_scans)
    return _semaphore


def _workdir_root() -> str:
    root = Path(settings.clone_workdir_path)
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def validate_repo_url(repo_url: str) -> None:
    """Reject non-http(s) schemes and hosts that resolve to loopback/private/link-local
    (SSRF + cloud-metadata 169.254.169.254 defense)."""
    parsed = urlparse(repo_url)
    if parsed.scheme not in ("http", "https"):
        raise CloudScanError("repo_url must be an http or https URL")
    host = parsed.hostname
    if not host:
        raise CloudScanError("repo_url has no host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise CloudScanError("repo_url host does not resolve")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise CloudScanError("repo_url resolves to a disallowed address")


def _sanitize(message: str, repo_token: str | None) -> str:
    if repo_token:
        message = message.replace(repo_token, "***")
    return message[:1000]


def _kill(proc: asyncio.subprocess.Process) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, AttributeError, OSError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass


async def _run(cmd: list[str], timeout: int, env: dict | None = None) -> tuple[int, bytes, bytes]:
    kwargs = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True  # own process group so a timeout kills children too
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        **kwargs,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        _kill(proc)
        raise CloudScanError(f"command timed out after {timeout}s: {cmd[0]}")
    return proc.returncode, out, err


async def _clone(repo_url: str, branch: str | None, workdir: str, repo_token: str | None) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if repo_token:
        # Inject the auth header via env config (not argv/URL) so the token never lands in `ps` or logs.
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: Bearer {repo_token}"
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, workdir]
    rc, _out, err = await _run(cmd, settings.scan_timeout_seconds, env=env)
    if rc != 0:
        raise CloudScanError(f"git clone failed (exit {rc}): {err.decode(errors='replace')}")


async def _scan_and_ingest(scan: Scan, workdir: str) -> None:
    cmd = [
        settings.scanner_binary_path,
        "scan",
        workdir,
        "--format",
        "json",
        "--enable-secrets",
        "--enable-sca",
        "--enable-framework-checks",
    ]
    rc, out, err = await _run(cmd, settings.scan_timeout_seconds)
    # Scanner exit codes: 0 clean, 1 findings found — both are successful runs with a report on stdout.
    if rc not in (0, 1):
        raise CloudScanError(f"scanner exited {rc}: {err.decode(errors='replace')}")
    report = GoReportIn.model_validate_json(out)
    json_path = artifact_store.write_json(scan.project_id, str(scan.id), out)
    await report_ingestion_service.ingest(scan, report, json_path)


async def _fail(scan: Scan, message: str) -> None:
    now = datetime.now(timezone.utc)
    scan.status = "failed"
    scan.error_message = message
    scan.completed_at = now
    scan.updated_at = now
    await scan.save()


async def run_cloud_scan(scan_id: str, repo_token: str | None = None) -> None:
    scan = await Scan.get(scan_id)
    if not scan or scan.scan_type != "cloud" or not scan.repo_url:
        return

    async with _sem():
        now = datetime.now(timezone.utc)
        scan.status = "running"
        scan.started_at = now
        scan.updated_at = now
        await scan.save()

        workdir = tempfile.mkdtemp(prefix="zs-clone-", dir=_workdir_root())
        try:
            validate_repo_url(scan.repo_url)
            await _clone(scan.repo_url, scan.branch, workdir, repo_token)
            await _scan_and_ingest(scan, workdir)  # ingest marks the scan completed
        except Exception as e:
            await _fail(scan, _sanitize(str(e), repo_token))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

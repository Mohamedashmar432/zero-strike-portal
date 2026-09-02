"""Server-side cloud scan execution.

For a scan_type="cloud" Scan: clone the repo into an ephemeral workdir, run the
baked-in Go scanner binary against it, ingest the report via the shared
report_ingestion_service, and delete the clone (crash-safe). Invoked only after
scan_queue_service has atomically claimed the scan (set status="running") —
this module no longer manages concurrency itself, see scan_queue_service.

Static analysis only — the target code is never executed — but git clone and the
SCA scanner hit the network, so: SSRF guard on repo_url, per-step timeouts, and
guaranteed workdir cleanup. Subprocesses run in a worker thread (see _run_sync)
so the same code path works on Windows (local dev) and Linux (container).
"""

import asyncio
import base64
import contextlib
import ipaddress
import os
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import structlog

from app.core.config import settings
from app.core.retry import retry_transient
from app.models.scan import Scan, ScanStage
from app.schemas.report import GoReportIn
from app.services import report_ingestion_service, workspace_settings_service

logger = structlog.get_logger(__name__)


class CloudScanError(Exception):
    """A recoverable cloud-scan failure; message is surfaced (sanitized) on the scan."""


class _TransientCloneError(CloudScanError):
    """A git-clone failure that looks like a network blip rather than a real
    auth/URL/branch problem -- worth a couple of quick retries."""


# Substrings from git's stderr that indicate a transient network condition. Deliberately
# narrow: retrying a genuine auth/URL/branch failure would just waste the scan's timeout
# budget three times over before surfacing an error the user could actually act on.
_TRANSIENT_GIT_PATTERNS = (
    "could not resolve host",
    "connection reset",
    "connection timed out",
    "the remote end hung up unexpectedly",
    "recv failure",
    "temporary failure in name resolution",
)


def _is_transient_git_error(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(pattern in lowered for pattern in _TRANSIENT_GIT_PATTERNS)


def scanner_available() -> bool:
    """Whether settings.scanner_binary_path currently resolves to a real executable — checked at
    startup (main.py's lifespan) so a misconfigured/missing binary is an immediate, loud log line
    instead of a silent surprise on the first cloud scan a user happens to try."""
    return shutil.which(settings.scanner_binary_path) is not None


def _workdir_root() -> str:
    # Empty setting => OS temp dir, so this resolves sensibly on Windows and Linux alike.
    base = settings.clone_workdir_path or str(Path(tempfile.gettempdir()) / "zs-clones")
    root = Path(base)
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


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the timed-out process and anything it spawned.

    `Popen.kill()` alone ends one process: on Windows that is literally just the
    direct child, and the scanner shells out to `git` for commit/branch metadata.
    A surviving grandchild keeps a handle on the clone workdir, which then fails
    to delete, so the leak is disk as well as CPU.
    """
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            timeout=30,
            check=False,
        )
    else:
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=30)


# How much of a killed process's stderr to keep. Enough for the last few scanner log lines
# (which name the file being parsed), small enough that it can't bloat Scan.error_message —
# _sanitize caps the whole message at 1000 chars downstream regardless.
_STDERR_TAIL_BYTES = 2000


def _stderr_tail(err_f) -> str:
    """Last few KB of a timed-out process's stderr, as a suffix for its error message.

    Best-effort: this runs on a failure path that must not be replaced by a second failure,
    so an unreadable temp file yields no suffix rather than an exception.
    """
    try:
        err_f.seek(0, os.SEEK_END)
        size = err_f.tell()
        err_f.seek(max(0, size - _STDERR_TAIL_BYTES))
        text = err_f.read().decode(errors="replace").strip()
    except Exception:
        return ""
    if not text:
        return ""
    return f" Last scanner output: {text}"


def _run_sync(cmd: list[str], timeout: int, env: dict | None = None) -> tuple[int, bytes, bytes]:
    # Popen with output to temp FILES rather than subprocess.run with pipes, on purpose.
    # subprocess.run(capture_output=True, timeout=...) reads through pipes, and its timeout
    # path is kill() followed by an *untimed* communicate() to drain them — so if anything
    # still holds the write end (a grandchild the Windows kill did not reach), that drain
    # never returns and the timeout that was supposed to bound this scan hangs forever
    # instead: the scan sits "running" with no report and no error, exactly the symptom a
    # large repo produced. Files also keep a multi-hundred-MB report off the Python heap.
    # A worker thread still runs this (see _run) so the same code path works on Windows dev
    # and Linux prod, unlike asyncio.create_subprocess_exec.
    try:
        with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
            proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, env=env)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                # Keep what the process had written before it was killed. A timeout used to
                # discard stderr entirely, throwing away the one line that says which file the
                # scanner was working on when the budget ran out — the most useful fact there is
                # about a large-repo hang, and the reason diagnosing one meant reading source.
                tail = _stderr_tail(err_f)
                if cmd[0] == settings.scanner_binary_path:
                    raise CloudScanError(
                        f"scan timed out after {timeout}s — the repository is too large to finish "
                        "in the current budget. Exclude large generated or vendored directories, "
                        f"or ask an administrator to raise SCAN_TIMEOUT_SECONDS.{tail}"
                    )
                raise CloudScanError(f"command timed out after {timeout}s: {cmd[0]}{tail}")
            out_f.seek(0)
            err_f.seek(0)
            return proc.returncode, out_f.read(), err_f.read()
    except FileNotFoundError:
        if cmd[0] == settings.scanner_binary_path:
            # Distinct from every other failure here: this is a portal misconfiguration (or a
            # process that never picked up a SCANNER_BINARY_PATH change — .env is only read at
            # startup), not something a user can fix by retrying or fixing their repo/token. Log
            # loudly so it's diagnosable from server logs alone, without reproducing a scan.
            logger.error(
                "Scanner binary not found at %r (SCANNER_BINARY_PATH) — every cloud scan will fail "
                "until this is fixed; restart the backend after correcting it.",
                cmd[0],
            )
            raise CloudScanError(
                f"ZeroStrike scanner is not available on this server (binary not found at "
                f"'{cmd[0]}'). This is a portal configuration issue, not a problem with your repo — "
                "contact an administrator."
            )
        logger.error("Required executable not found: %r", cmd[0])
        raise CloudScanError(f"executable not found: {cmd[0]}")


async def _run(cmd: list[str], timeout: int, env: dict | None = None) -> tuple[int, bytes, bytes]:
    return await asyncio.to_thread(_run_sync, cmd, timeout, env)


async def _clone(
    repo_url: str, branch: str | None, workdir: str, repo_token: str | None, auth_scheme: str = "bearer"
) -> None:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if repo_token:
        # Inject the auth header via env config (not argv/URL) so the token never lands in `ps` or logs.
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        if auth_scheme == "basic":
            # GitHub tokens (PAT or OAuth) and Azure DevOps PATs all authenticate git-over-HTTPS via
            # HTTP Basic (token as password) — Bearer here gets silently rejected instead (see
            # repo_token_auth_scheme on Scan for why this matters). The username must be NON-EMPTY:
            # Azure DevOps tolerates ":PAT", GitHub 401s on it and git then falls back to the
            # credential helper ("could not read Username ... terminal prompts disabled").
            # "x-access-token" is GitHub's own placeholder and Azure DevOps ignores the username.
            basic_token = base64.b64encode(f"x-access-token:{repo_token}".encode()).decode()
            env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: Basic {basic_token}"
        else:
            env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: Bearer {repo_token}"
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, workdir]

    @retry_transient((_TransientCloneError,), max_attempts=3, base_delay=2.0)
    async def _do_clone() -> None:
        # A retried attempt must start from an empty dir -- git clone refuses a non-empty
        # target, and a failed attempt can leave partial content behind in one that already existed.
        shutil.rmtree(workdir, ignore_errors=True)
        os.makedirs(workdir, exist_ok=True)
        rc, _out, err = await _run(cmd, settings.scan_timeout_seconds, env=env)
        if rc != 0:
            message = err.decode(errors="replace")
            if _is_transient_git_error(message):
                raise _TransientCloneError(f"git clone failed (exit {rc}): {message}")
            raise CloudScanError(f"git clone failed (exit {rc}): {message}")

    await _do_clone()


# Vendored/generated content inflates parse + taint-analysis memory without adding real
# findings (it's third-party or machine-generated, not code the user owns) -- excluded by
# default on every cloud scan. --exclude-dir matches directory names anywhere in the tree.
_DEFAULT_EXCLUDE_DIRS = ("node_modules", "vendor", "dist", "build", ".git", "bin", "obj", "target")


async def _scan_and_ingest(scan: Scan, workdir: str) -> None:
    # Which analysers run is workspace policy with a per-project override; the defaults are
    # all-on, so this produces the same argv as the previously hardcoded flags until an
    # admin turns something off.
    project = await workspace_settings_service.load_project(scan.project_id)
    options = await workspace_settings_service.effective_scan_options(project)
    cmd = [
        settings.scanner_binary_path,
        "scan",
        workdir,
        "--format",
        "json",
        "--workers",
        str(settings.scanner_max_workers),
    ]
    if options.enable_secrets:
        cmd.append("--enable-secrets")
    if options.enable_sca:
        cmd.append("--enable-sca")
    if options.enable_framework_checks:
        cmd.append("--enable-framework-checks")
    for d in _DEFAULT_EXCLUDE_DIRS:
        cmd += ["--exclude-dir", d]
    rc, out, err = await _run(cmd, settings.scan_timeout_seconds)
    # Scanner exit codes: 0 clean, 1 findings found — both are successful runs with a report on stdout.
    if rc not in (0, 1):
        if rc == -9:
            # subprocess.run reports a POSIX kill-by-signal as -signum. -9 is SIGKILL, which the
            # scanner never sends itself -- this is the container's OOM killer (or a runner-enforced
            # hard kill). Distinct message so it's diagnosable from the scan's error_message alone,
            # without cross-referencing infra logs.
            raise CloudScanError(
                "scanner was killed (out of memory) -- the repository is likely too large or "
                "contains huge generated/vendored files for the scanner's available memory. Try "
                "excluding additional large directories or increasing the scan container's memory."
            )
        raise CloudScanError(f"scanner exited {rc}: {err.decode(errors='replace')}")
    await _stage(scan, "ingesting")
    report = GoReportIn.model_validate_json(out)
    await report_ingestion_service.ingest(scan, report, out.decode("utf-8", errors="replace"))


async def _stage(scan: Scan, stage: ScanStage) -> None:
    """Record which phase of the pipeline this scan is in. Diagnostics only.

    Advisory by construction: the queue claims and reaps on `status` alone, so nothing branches
    on `stage` and a failed write here must not fail the scan — a scan that finishes without
    having said it was cloning is a worse log, not a worse scan.

    The write also refreshes updated_at, but phase boundaries alone are NOT a heartbeat: the
    phase that takes the time has no boundary in the middle of it, so a long scan still went
    stale and was reaped as crashed. `_heartbeat` is what actually keeps the clock moving; this
    just happens to also touch it (see docs/OBSERVABILITY_SCAN_AND_AI.md).
    """
    now = datetime.now(timezone.utc)
    scan.stage = stage
    scan.stage_started_at = now
    scan.updated_at = now
    try:
        await scan.save()
    except Exception:
        logger.warning("could not record stage %s for scan %s", stage, scan.id, exc_info=True)


# How often a running scan touches updated_at while a subprocess is working. Only has to be
# comfortably inside the reap window (scan_timeout_seconds * queue_stuck_multiplier, 45 min on
# the defaults), so this is one tiny $set per scan per 30s -- nothing next to a clone or a scan.
_HEARTBEAT_SECONDS = 30

# Bound at import on purpose. Several tests patch asyncio.sleep globally to skip retry backoff,
# and a heartbeat whose only yield point is a patched-to-instant sleep becomes a busy loop that
# starves the event loop -- i.e. an unrelated patch silently disables the liveness mechanism.
# Holding the real one keeps this loop's timing independent of anything else's.
_real_sleep = asyncio.sleep


async def _heartbeat(scan: Scan) -> None:
    """Keep `updated_at` moving for as long as this worker is actually working on the scan.

    `_stage` only writes at phase boundaries, and the phase that takes the time -- `scanning` --
    has no boundary in the middle of it. So a scan that legitimately spent longer in the scanner
    than the reap window looked, to the reaper, exactly like one whose worker had died: it was
    failed with "worker likely crashed mid-scan" while the subprocess was still running fine.

    With this, the two cases finally separate. A worker that dies takes this task with it, so a
    reap once again means what it says; a scan that is merely slow is bounded by the subprocess's
    own timeout instead, which fails it with a message naming the timeout and how to raise it.
    """
    while True:
        await _real_sleep(_HEARTBEAT_SECONDS)
        try:
            await scan.set({Scan.updated_at: datetime.now(timezone.utc)})
        except Exception:
            # Same contract as _stage: bookkeeping must never take down the scan it describes.
            # A missed beat costs nothing; only a run of them past the reap window matters.
            logger.warning("heartbeat write failed for scan %s", scan.id, exc_info=True)


@contextlib.asynccontextmanager
async def _beating(scan: Scan):
    """Run the body with a heartbeat, and always stop it before the caller reacts to failure."""
    task = asyncio.create_task(_heartbeat(scan))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _fail(scan: Scan, message: str) -> None:
    now = datetime.now(timezone.utc)
    scan.status = "failed"
    scan.error_message = message
    scan.completed_at = now
    scan.updated_at = now
    # Leave `stage` set: on a terminal failure it is the record of *where* the pipeline stopped,
    # which is the whole point of having it. It is only meaningful alongside status="failed".
    await scan.save()

    # A failure frees a concurrency slot — nudge the queue rather than waiting for the next poll tick.
    from app.services import notification_service, scan_queue_service

    await scan_queue_service.drain_queue()
    await notification_service.notify(
        "scan.failed",
        project_id=scan.project_id,
        title="Scan failed",
        body=message,
        link=f"/projects/{scan.project_id}/scans/{scan.id}",
        severity="error",
    )


async def run_cloud_scan(scan_id: str, repo_token: str | None = None, repo_token_auth_scheme: str = "bearer") -> None:
    """Clone + scan + ingest an already-claimed scan (status="running", set by scan_queue_service)."""
    scan = await Scan.get(scan_id)
    if not scan or scan.scan_type != "cloud" or not scan.repo_url:
        return

    workdir = tempfile.mkdtemp(prefix="zs-clone-", dir=_workdir_root())
    try:
        # The heartbeat covers the whole pipeline, not just the scanner: an 872MB clone is long
        # enough to be reaped mid-clone on its own. It stops before the except block below, so a
        # real failure is never racing a beat.
        async with _beating(scan):
            await _stage(scan, "validating")
            validate_repo_url(scan.repo_url)
            await _stage(scan, "cloning")
            await _clone(scan.repo_url, scan.branch, workdir, repo_token, repo_token_auth_scheme)
            await _stage(scan, "scanning")
            await _scan_and_ingest(scan, workdir)  # ingest marks the scan completed
    except Exception as e:
        message = _sanitize(str(e), repo_token)
        # CloudScanError covers every expected failure mode (bad repo_url, clone/scanner failure,
        # timeout) and is already a clear, complete message — a traceback would only point at
        # subprocess.run internals. Anything else is unexpected (e.g. a bad ingestion parse) and
        # gets a full traceback since that's a real bug worth debugging from the log alone.
        logger.error(
            "Cloud scan %s failed: %s (repo=%s branch=%s)",
            scan_id,
            message,
            scan.repo_url,
            scan.branch or "<default>",
            exc_info=not isinstance(e, CloudScanError),
        )
        await _fail(scan, message)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

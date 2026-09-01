"""Generalized git workspace for the AI Auto-Fix apply step (see docs/AI_AUTOFIX_DESIGN.md).

Unlike cloud_scan_service (single-shot clone-scan-delete), remediation needs a cwd-aware git
runner (checkout/commit/push into the clone), a base-branch clone that can push a new branch, and
a scanner run that returns findings WITHOUT creating a Scan doc or ingesting (the validation gate).
It reuses the one public SSRF guard (cloud_scan_service.validate_repo_url); the small subprocess /
token-env plumbing is intentionally kept separate from cloud_scan_service so refactoring one path
can't regress the other.

ponytail: the token-env + subprocess runner overlap ~30 lines with cloud_scan_service; consolidate
into one shared primitive if a third caller appears.
"""

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import structlog

from app.core.config import settings
from app.schemas.report import GoReportIn
from app.services.cloud_scan_service import validate_repo_url  # single SSRF source of truth

logger = structlog.get_logger(__name__)

__all__ = ["GitWorkspaceError", "validate_repo_url", "workdir_root", "sanitize", "clone_repo", "git", "run_scanner"]


class GitWorkspaceError(Exception):
    """A recoverable remediation-workspace failure; message is surfaced (sanitized) on the proposal."""


def workdir_root() -> str:
    base = settings.clone_workdir_path or str(Path(tempfile.gettempdir()) / "zs-clones")
    root = Path(base)
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def sanitize(message: str, token: str | None) -> str:
    if token:
        message = message.replace(token, "***")
    return message[:1000]


def _token_env(token: str | None, auth_scheme: str) -> dict:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    if token:
        # Auth header via env config (not argv/URL) so the token never lands in `ps`/logs.
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        if auth_scheme == "basic":
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: Basic {basic}"
        else:
            env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: Bearer {token}"
    return env


def _run_sync(cmd: list[str], timeout: int, env: dict | None, cwd: str | None) -> tuple[int, bytes, bytes]:
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout, env=env, cwd=cwd, check=False)
    except subprocess.TimeoutExpired:
        raise GitWorkspaceError(f"command timed out after {timeout}s: {cmd[0]}")
    except FileNotFoundError:
        raise GitWorkspaceError(f"executable not found: {cmd[0]}")
    return proc.returncode, proc.stdout or b"", proc.stderr or b""


async def _run(cmd: list[str], timeout: int, env: dict | None = None, cwd: str | None = None):
    return await asyncio.to_thread(_run_sync, cmd, timeout, env, cwd)


async def clone_repo(
    repo_url: str,
    branch: str | None,
    workdir: str,
    token: str | None = None,
    auth_scheme: str = "bearer",
    *,
    depth: int = 1,
    single_branch: bool = True,
) -> None:
    """Clone into an empty workdir. depth=1 + single_branch is enough to push a NEW branch (its only
    parent is the fetched tip); if a push is later rejected as shallow, call `git(..., ["fetch",
    "--unshallow", "origin"])` and retry once (see ai_remediation_apply_service)."""
    env = _token_env(token, auth_scheme)
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)
    cmd = ["git", "clone"]
    if depth:
        cmd += ["--depth", str(depth)]
    if single_branch:
        cmd += ["--single-branch"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, workdir]
    rc, _out, err = await _run(cmd, settings.remediation_job_timeout_seconds, env=env)
    if rc != 0:
        raise GitWorkspaceError(f"git clone failed (exit {rc}): {err.decode(errors='replace')}")


async def git(
    args: list[str], workdir: str, token: str | None = None, auth_scheme: str = "bearer", timeout: int = 120
) -> tuple[int, str, str]:
    """Run `git -C <workdir> <args>`. A token env is attached only when a token is given (needed for
    push/fetch, harmless otherwise). Returns (returncode, stdout, stderr) decoded."""
    env = _token_env(token, auth_scheme) if token else None
    rc, out, err = await _run(["git", "-C", workdir, *args], timeout, env=env, cwd=None)
    return rc, out.decode(errors="replace"), err.decode(errors="replace")


async def run_scanner(workdir: str) -> tuple[GoReportIn, str]:
    """Run the ZeroStrike scanner over workdir and return (parsed report, raw json). No Scan doc,
    no ingest -- this is the lighter wrapper the validation gate uses to diff findings before/after
    a patch. Exit 0 (clean) and 1 (findings) are both success, matching cloud_scan_service."""
    cmd = [
        settings.scanner_binary_path, "scan", workdir,
        "--format", "json", "--enable-secrets", "--enable-sca", "--enable-framework-checks",
    ]
    rc, out, err = await _run(cmd, settings.remediation_job_timeout_seconds)
    if rc not in (0, 1):
        raise GitWorkspaceError(f"scanner exited {rc}: {err.decode(errors='replace')}")
    raw = out.decode("utf-8", errors="replace")
    return GoReportIn.model_validate_json(out), raw

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
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import structlog

from app.core.config import settings
from app.schemas.report import GoReportIn
from app.services.cloud_scan_service import (  # single SSRF source of truth
    CloudScanError,
    git_hardening_entries,
    validate_repo_url,
)

logger = structlog.get_logger(__name__)

__all__ = [
    "GitWorkspaceError", "validate_repo_url", "workdir_root", "sanitize", "clone_repo", "git", "run_scanner",
    "remote_head",
]


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


def _token_env(
    token: str | None, auth_scheme: str, repo_url: str | None = None, pinned_ips: list[str] | None = None
) -> dict:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    # `credential.helper` is always neutralised, token or not. GIT_TERMINAL_PROMPT only suppresses
    # git's *own* username prompt; a configured helper is consulted first and can block forever on
    # an interactive picker. The portable Git on this machine ships
    # `credential.helper=helper-selector`, so cloning a private or non-existent repo hung for the
    # whole `remediation_job_timeout_seconds` (observed: 600s -> "command timed out") instead of
    # failing in about a second with a readable auth error.
    entries: list[tuple[str, str]] = [("credential.helper", "")]
    if token:
        # Auth header via env config (not argv/URL) so the token never lands in `ps`/logs.
        if auth_scheme == "basic":
            basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            entries.append(("http.extraHeader", f"AUTHORIZATION: Basic {basic}"))
        else:
            entries.append(("http.extraHeader", f"AUTHORIZATION: Bearer {token}"))

    if repo_url:
        entries += git_hardening_entries(repo_url, pinned_ips)

    env["GIT_CONFIG_COUNT"] = str(len(entries))
    for i, (key, value) in enumerate(entries):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
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
    # Validated here, not left to callers: an unvalidated `--upload-pack=<cmd>` clone_url is RCE.
    try:
        pinned_ips = validate_repo_url(repo_url)
    except CloudScanError as exc:
        raise GitWorkspaceError(str(exc))
    env = _token_env(token, auth_scheme, repo_url, pinned_ips)
    shutil.rmtree(workdir, ignore_errors=True)
    os.makedirs(workdir, exist_ok=True)
    cmd = ["git", "clone"]
    if depth:
        cmd += ["--depth", str(depth)]
    if single_branch:
        cmd += ["--single-branch"]
    if branch:
        cmd += ["--branch", branch]
    cmd += ["--", repo_url, workdir]
    rc, _out, err = await _run(cmd, settings.remediation_job_timeout_seconds, env=env)
    if rc != 0:
        raise GitWorkspaceError(f"git clone failed (exit {rc}): {err.decode(errors='replace')}")


_BRANCH_RE = re.compile(r"[A-Za-z0-9._/-]+")


async def remote_head(
    repo_url: str, branch: str, token: str | None = None, auth_scheme: str = "bearer", timeout: int = 30
) -> str:
    """Head commit sha of `branch` on the remote, via `git ls-remote` (no clone). SSRF-validated and
    pinned like a clone; the token travels in GIT_CONFIG_* env, never argv. Raises GitWorkspaceError
    with a sanitized message on any failure, including a branch that does not exist remotely."""
    if not _BRANCH_RE.fullmatch(branch) or branch.startswith("-") or ".." in branch:
        raise GitWorkspaceError("invalid branch name")
    try:
        pinned_ips = validate_repo_url(repo_url)
    except CloudScanError as exc:
        raise GitWorkspaceError(str(exc))
    env = _token_env(token, auth_scheme, repo_url, pinned_ips)
    ref = f"refs/heads/{branch}"
    try:
        rc, out, err = await _run(["git", "ls-remote", "--", repo_url, ref], timeout, env=env)
    except GitWorkspaceError as exc:
        raise GitWorkspaceError(sanitize(str(exc), token))
    if rc != 0:
        raise GitWorkspaceError(sanitize(f"git ls-remote failed (exit {rc}): {err.decode(errors='replace')}", token))
    for line in out.decode(errors="replace").splitlines():
        sha, _, name = line.partition("	")
        if name.strip() == ref and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
            return sha
    raise GitWorkspaceError(f"branch '{branch}' was not found on the remote")


async def git(
    args: list[str], workdir: str, token: str | None = None, auth_scheme: str = "bearer", timeout: int = 120
) -> tuple[int, str, str]:
    """Run `git -C <workdir> <args>`. A token env is attached only when a token is given (needed for
    push/fetch, harmless otherwise). Returns (returncode, stdout, stderr) decoded."""
    env = _token_env(token, auth_scheme) if token else None
    rc, out, err = await _run(["git", "-C", workdir, *args], timeout, env=env, cwd=None)
    return rc, out.decode(errors="replace"), err.decode(errors="replace")


async def run_scanner(workdir: str) -> tuple[GoReportIn, str]:
    """Run the thinkShield scanner over workdir and return (parsed report, raw json). No Scan doc,
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

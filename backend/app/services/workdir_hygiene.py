"""Clone-workdir hygiene: logged cleanup, stale-dir sweep, free-disk preflight, size cap, usage.

Shared by cloud_scan_service and git_workspace (AI remediation), so it imports neither. Every
function takes the workdir root as an argument; the callers own resolving it.
See docs/CLONE_LIFECYCLE_AND_SCAN_REUSE.md.

Why there is no `git clone --filter=blob:limit=N`: a partial clone only defers large blobs, and
`git checkout` of the tip then fetches every one of them it needs to populate the working tree --
so the bytes still land on disk, plus a second round trip. Verified: a 6 MB blob cloned with
`--depth 1 --filter=blob:limit=1m` is present in the worktree and `rev-list --missing=print` reports
nothing missing. Avoiding the download would need `--no-checkout`/sparse checkout and a decision about
which files the scanner may skip, which is a scanner-side concern. The guards here are therefore the
free-disk preflight (refuse before cloning) and the post-clone size cap (refuse before scanning).
"""

import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

# mkdtemp prefixes in use: cloud_scan_service "zs-clone-", remediation "zs-remediate-" and
# "zs-remediate-propose-" (the latter matches the former).
WORKDIR_PREFIXES = ("zs-clone-", "zs-remediate-")

_MB = 1024 * 1024


class WorkdirError(Exception):
    """A readable refusal (disk too full, repo too large). Callers re-raise it as their own error."""


def rmtree_logged(path: str | Path) -> None:
    """Best-effort recursive delete that says what it could not remove. Never raises: cleanup runs in
    `finally` blocks and must not fail (or mask the failure of) the scan it is cleaning up after."""

    def _log(func, failed_path, exc) -> None:
        logger.warning(
            "workdir cleanup failed", path=str(failed_path), operation=getattr(func, "__name__", str(func)),
            error=repr(exc),
        )

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=lambda f, p, e: _log(f, p, e))
        else:  # `onerror` is deprecated from 3.12 but is the only spelling on 3.11
            shutil.rmtree(path, onerror=lambda f, p, ei: _log(f, p, ei[1]))
    except Exception as exc:  # the handler itself failing, or a vanished root
        _log(rmtree_logged, path, exc)


def dir_size_bytes(path: str | Path) -> int:
    """Total size of regular files under `path` (symlinks not followed). Missing entries are skipped."""
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except OSError:
                continue
            if not os.path.islink(os.path.join(dirpath, name)):
                total += st.st_size
    return total


def free_mb(root: str | Path) -> int:
    return shutil.disk_usage(root).free // _MB


def preflight_free_disk(root: str | Path, min_free_mb: int) -> None:
    """Refuse to start a clone when the volume is nearly full, instead of filling it."""
    if min_free_mb <= 0:
        return
    free = free_mb(root)
    if free < min_free_mb:
        raise WorkdirError(
            f"The scan server is low on disk space ({free} MB free, {min_free_mb} MB required to start a "
            "clone). This is a portal capacity issue, not a problem with your repository -- try again "
            "shortly or contact an administrator."
        )


def check_repo_size(workdir: str | Path, max_repo_mb: int) -> None:
    """Fail a clone that landed bigger than the cap, before the scanner reads it."""
    if max_repo_mb <= 0:
        return
    size_mb = dir_size_bytes(workdir) // _MB
    if size_mb > max_repo_mb:
        raise WorkdirError(
            f"The cloned repository is {size_mb} MB, over the {max_repo_mb} MB limit for server-side scans. "
            "Scan it with the CLI or CI integration instead, or ask an administrator to raise CLONE_MAX_REPO_MB."
        )


def _is_workdir(name: str) -> bool:
    return name.startswith(WORKDIR_PREFIXES)


def sweep_stale_workdirs(root: str | Path, max_age_seconds: float, *, now: float | None = None) -> int:
    """Delete `zs-clone-*` / `zs-remediate-*` directories under `root` last modified more than
    `max_age_seconds` ago; returns how many were removed. Age-based on purpose: callers pass a window
    longer than any scan or remediation job may run (the reap window), so a live workdir is never
    touched, and no registry of live workdirs has to be shared across replicas. Never raises."""
    removed = 0
    cutoff = (time.time() if now is None else now) - max_age_seconds
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0
    for entry in entries:
        try:
            if not (entry.is_dir(follow_symlinks=False) and _is_workdir(entry.name)):
                continue
            if entry.stat(follow_symlinks=False).st_mtime >= cutoff:
                continue
        except OSError:
            continue
        rmtree_logged(entry.path)
        if not os.path.exists(entry.path):
            removed += 1
            logger.warning("removed stale clone workdir", path=entry.path)
    return removed


@dataclass(frozen=True)
class WorkdirUsage:
    count: int
    total_mb: int
    free_mb: int


def usage(root: str | Path) -> WorkdirUsage:
    """Live clone workdirs under `root`: how many, how big, and how much room is left on the volume."""
    count, total = 0, 0
    try:
        for entry in os.scandir(root):
            if entry.is_dir(follow_symlinks=False) and _is_workdir(entry.name):
                count += 1
                total += dir_size_bytes(entry.path)
    except OSError:
        pass
    try:
        free = free_mb(root)
    except OSError:
        free = 0
    return WorkdirUsage(count=count, total_mb=total // _MB, free_mb=free)

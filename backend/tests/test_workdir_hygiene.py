"""Clone-workdir disk safety (docs/CLONE_LIFECYCLE_AND_SCAN_REUSE.md, phase B)."""

import asyncio
import os
import time
from pathlib import Path

import pytest
import structlog

import app.services.cloud_scan_service as css
from app.models.scan import Scan
from app.services import git_workspace, scan_queue_service, workdir_hygiene
from tests.test_cloud_scan_service import (
    _as_popen,
    _FakeCompleted,
    _make_cloud_scan,
    _patch_subprocess,
)

MB = 1024 * 1024


def _age(path: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(path, (t, t))


# --- sweep ------------------------------------------------------------------------------------


def test_sweep_deletes_only_old_clone_and_remediation_dirs(tmp_path):
    old_clone = tmp_path / "zs-clone-old"
    old_fix = tmp_path / "zs-remediate-old"
    old_propose = tmp_path / "zs-remediate-propose-old"
    young_clone = tmp_path / "zs-clone-young"
    unrelated = tmp_path / "somebody-elses-dir"
    for d in (old_clone, old_fix, old_propose, young_clone, unrelated):
        d.mkdir()
        (d / "f.txt").write_text("x")
    for d in (old_clone, old_fix, old_propose, unrelated):
        _age(d, 10_000)
    stray_file = tmp_path / "zs-clone-a-file"
    stray_file.write_text("x")
    _age(stray_file, 10_000)

    removed = workdir_hygiene.sweep_stale_workdirs(tmp_path, 3_600)

    assert removed == 3
    assert not old_clone.exists() and not old_fix.exists() and not old_propose.exists()
    assert young_clone.exists()  # a live scan's workdir is never touched
    assert unrelated.exists() and stray_file.exists()  # not ours


def test_sweep_on_a_missing_root_is_a_noop(tmp_path):
    assert workdir_hygiene.sweep_stale_workdirs(tmp_path / "nope", 1) == 0


def test_queue_sweep_uses_the_reap_window(client, monkeypatch, tmp_path):
    monkeypatch.setattr(css.settings, "clone_workdir_path", str(tmp_path))
    monkeypatch.setattr(css.settings, "scan_timeout_seconds", 100)
    monkeypatch.setattr(css.settings, "queue_stuck_multiplier", 3)
    monkeypatch.setattr(css.settings, "remediation_job_timeout_seconds", 10)
    assert scan_queue_service.stale_workdir_age_seconds() == 300
    inside_window = tmp_path / "zs-clone-inside"
    outside_window = tmp_path / "zs-clone-outside"
    inside_window.mkdir()
    outside_window.mkdir()
    _age(inside_window, 250)
    _age(outside_window, 400)

    assert asyncio.run(scan_queue_service.sweep_stale_workdirs()) == 1

    assert inside_window.exists() and not outside_window.exists()


def test_poll_loop_sweeps_on_each_tick(client, monkeypatch):
    calls = []

    async def noop():
        return None

    async def sweep():
        calls.append("sweep")
        return 0

    ticks = {"n": 0}

    async def fake_sleep(_seconds):
        ticks["n"] += 1
        if ticks["n"] > 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(scan_queue_service, "reap_stuck_scans", noop)
    monkeypatch.setattr(scan_queue_service, "drain_queue", noop)
    monkeypatch.setattr(scan_queue_service, "sweep_stale_workdirs", sweep)
    monkeypatch.setattr(scan_queue_service.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scan_queue_service.poll_loop())

    assert calls == ["sweep", "sweep"]


# --- logged cleanup ---------------------------------------------------------------------------


def test_rmtree_failure_is_logged_not_raised(tmp_path, monkeypatch):
    target = tmp_path / "zs-clone-x"
    target.mkdir()
    (target / "locked.txt").write_text("x")
    real_unlink = os.unlink

    def fake_unlink(path, *a, **kw):
        if "locked" in str(path):
            raise PermissionError("held open")
        return real_unlink(path, *a, **kw)

    monkeypatch.setattr(os, "unlink", fake_unlink)
    with structlog.testing.capture_logs() as logs:
        workdir_hygiene.rmtree_logged(target)  # must not raise

    failures = [e for e in logs if e["event"] == "workdir cleanup failed"]
    assert failures and "locked.txt" in failures[0]["path"] and "held open" in failures[0]["error"]


def test_scan_cleanup_goes_through_the_logged_helper(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path)
    seen = []
    monkeypatch.setattr(workdir_hygiene, "rmtree_logged", lambda p: seen.append(str(p)))

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        return await Scan.get(scan.id)

    assert asyncio.run(run()).status == "completed"
    assert seen


# --- free-disk preflight ----------------------------------------------------------------------


def test_preflight_below_threshold_fails_the_scan_readably_without_cloning(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path)
    monkeypatch.setattr(css.settings, "clone_min_free_mb", 10**12)
    git_calls = []

    def fake_run(cmd, **kwargs):
        git_calls.append(cmd[0])
        return _FakeCompleted(0, b"", b"")

    monkeypatch.setattr(css.subprocess, "Popen", _as_popen(fake_run))

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        return await Scan.get(scan.id)

    scan = asyncio.run(run())
    assert scan.status == "failed"
    assert "low on disk space" in scan.error_message and "not a problem with your repository" in scan.error_message
    assert git_calls == []  # refused before any clone
    assert [p for p in tmp_path.iterdir() if p.name.startswith("zs-clone-")] == []


def test_preflight_passes_and_zero_disables(tmp_path):
    workdir_hygiene.preflight_free_disk(tmp_path, 1)
    workdir_hygiene.preflight_free_disk(tmp_path, 0)
    with pytest.raises(workdir_hygiene.WorkdirError):
        workdir_hygiene.preflight_free_disk(tmp_path, 10**12)


# --- size cap ---------------------------------------------------------------------------------


def test_oversized_clone_fails_the_scan_before_the_scanner_runs(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path)
    monkeypatch.setattr(css.settings, "clone_max_repo_mb", 1)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            (Path(cmd[-1]) / "blob.bin").write_bytes(bytes(3 * MB))
            return _FakeCompleted(0, b"", b"")
        raise AssertionError("scanner must not run on an oversized clone")

    monkeypatch.setattr(css.subprocess, "Popen", _as_popen(fake_run))

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        return await Scan.get(scan.id)

    scan = asyncio.run(run())
    assert scan.status == "failed"
    assert "3 MB, over the 1 MB limit" in scan.error_message
    assert [p for p in tmp_path.iterdir() if p.name.startswith("zs-clone-")] == []


def test_clone_within_the_cap_is_scanned(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path)
    monkeypatch.setattr(css.settings, "clone_max_repo_mb", 1)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        return await Scan.get(scan.id)

    assert asyncio.run(run()).status == "completed"


def test_check_repo_size_counts_nested_files(tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    (tmp_path / "a" / "b" / "x.bin").write_bytes(bytes(2 * MB))
    assert workdir_hygiene.dir_size_bytes(tmp_path) == 2 * MB
    with pytest.raises(workdir_hygiene.WorkdirError, match="2 MB, over the 1 MB"):
        workdir_hygiene.check_repo_size(tmp_path, 1)
    workdir_hygiene.check_repo_size(tmp_path, 2)
    workdir_hygiene.check_repo_size(tmp_path, 0)


# --- remediation clone (git_workspace) --------------------------------------------------------


def _remediation_clone(monkeypatch, tmp_path, *, size_mb=0):
    monkeypatch.setattr(git_workspace.settings, "clone_workdir_path", str(tmp_path))
    monkeypatch.setattr(git_workspace, "validate_repo_url", lambda url: [])

    async def fake_run(cmd, timeout, env=None, cwd=None):
        if size_mb:
            (Path(cmd[-1]) / "blob.bin").write_bytes(bytes(size_mb * MB))
        return 0, b"", b""

    monkeypatch.setattr(git_workspace, "_run", fake_run)


def test_remediation_clone_over_the_cap_is_a_readable_error(monkeypatch, tmp_path):
    _remediation_clone(monkeypatch, tmp_path, size_mb=2)
    monkeypatch.setattr(git_workspace.settings, "clone_max_repo_mb", 1)
    with pytest.raises(git_workspace.GitWorkspaceError, match="over the 1 MB limit"):
        asyncio.run(git_workspace.clone_repo("https://github.com/o/r", "main", str(tmp_path / "wd")))


def test_remediation_clone_refused_on_a_full_disk(monkeypatch, tmp_path):
    _remediation_clone(monkeypatch, tmp_path)
    monkeypatch.setattr(git_workspace.settings, "clone_min_free_mb", 10**12)
    with pytest.raises(git_workspace.GitWorkspaceError, match="low on disk space"):
        asyncio.run(git_workspace.clone_repo("https://github.com/o/r", "main", str(tmp_path / "wd")))
    assert not (tmp_path / "wd").exists()

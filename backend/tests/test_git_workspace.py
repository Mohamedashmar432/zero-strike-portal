"""Unit tests for git_workspace helpers (no DB). Subprocess is mocked at the _run boundary."""

import asyncio
import base64

import pytest

from app.services import git_workspace
from app.services.git_workspace import GitWorkspaceError, _token_env


def test_token_env_basic_and_bearer():
    basic = _token_env("tok", "basic")
    assert basic["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: Basic {base64.b64encode(b'x-access-token:tok').decode()}"
    assert basic["GIT_TERMINAL_PROMPT"] == "0"
    bearer = _token_env("tok", "bearer")
    assert bearer["GIT_CONFIG_VALUE_0"] == "AUTHORIZATION: Bearer tok"
    assert "GIT_CONFIG_KEY_0" not in _token_env(None, "bearer")  # no token -> no auth header


def test_run_scanner_parses_and_rejects_bad_exit(monkeypatch):
    async def fake_run(cmd, timeout, env=None, cwd=None):
        return 1, b'{"Findings": [{"Fingerprint": "fp1", "Severity": "high"}]}', b""

    monkeypatch.setattr(git_workspace, "_run", fake_run)
    report, raw = asyncio.run(git_workspace.run_scanner("/tmp/x"))
    assert len(report.findings) == 1 and report.findings[0].fingerprint == "fp1"
    assert "fp1" in raw

    async def fake_bad(cmd, timeout, env=None, cwd=None):
        return 3, b"", b"boom"

    monkeypatch.setattr(git_workspace, "_run", fake_bad)
    with pytest.raises(GitWorkspaceError):
        asyncio.run(git_workspace.run_scanner("/tmp/x"))


def test_clone_repo_raises_on_nonzero(monkeypatch, tmp_path):
    async def fake_run(cmd, timeout, env=None, cwd=None):
        return 128, b"", b"fatal: Authentication failed"

    monkeypatch.setattr(git_workspace, "_run", fake_run)
    with pytest.raises(GitWorkspaceError):
        asyncio.run(git_workspace.clone_repo("https://x/y", "main", str(tmp_path / "wd"), "tok", "basic"))

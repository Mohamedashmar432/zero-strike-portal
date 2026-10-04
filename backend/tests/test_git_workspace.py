"""Unit tests for git_workspace helpers (no DB). Subprocess is mocked at the _run boundary."""

import asyncio
import base64

import pytest

from app.services import git_workspace
from app.services.git_workspace import GitWorkspaceError, _token_env


def _config_pairs(env: dict) -> list[tuple[str, str]]:
    """Read back the GIT_CONFIG_COUNT/KEY_n/VALUE_n triple as ordered pairs."""
    return [
        (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"])
        for i in range(int(env["GIT_CONFIG_COUNT"]))
    ]


def test_token_env_always_neutralises_the_credential_helper():
    """Regression: a configured credential helper is consulted before GIT_TERMINAL_PROMPT, so
    leaving it in place let a private/non-existent repo hang on an interactive picker for the whole
    clone timeout (600s) instead of failing in ~1s with a readable auth error."""
    for env in (_token_env(None, "bearer"), _token_env("tok", "basic"), _token_env("tok", "bearer")):
        assert ("credential.helper", "") in _config_pairs(env)
        assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_token_env_basic_and_bearer():
    basic = _token_env("tok", "basic")
    assert (
        "http.extraHeader",
        f"AUTHORIZATION: Basic {base64.b64encode(b'x-access-token:tok').decode()}",
    ) in _config_pairs(basic)
    assert ("http.extraHeader", "AUTHORIZATION: Bearer tok") in _config_pairs(_token_env("tok", "bearer"))
    # No token -> the helper is still neutralised, but no auth header is emitted.
    no_token = _token_env(None, "bearer")
    assert not any(k == "http.extraHeader" for k, _ in _config_pairs(no_token))


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
    monkeypatch.setattr(git_workspace, "validate_repo_url", lambda url: ["93.184.216.34"])
    with pytest.raises(GitWorkspaceError, match="Authentication failed"):
        asyncio.run(git_workspace.clone_repo("https://x/y", "main", str(tmp_path / "wd"), "tok", "basic"))

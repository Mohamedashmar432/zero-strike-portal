"""Repo URL hardening: option injection (RCE), redirect following, DNS-rebinding pin, non-global IPs."""

import asyncio
import socket

import pytest

from app.services import cloud_scan_service as css
from app.services import git_workspace
from app.services.git_workspace import GitWorkspaceError
from tests.test_auth_flow import register_and_login


def _resolve_to(monkeypatch, ip):
    family = socket.AF_INET6 if ":" in ip else socket.AF_INET
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda host, port, *a, **kw: [(family, socket.SOCK_STREAM, 6, "", (ip, 0))]
    )


def _pairs(env):
    return dict(
        (env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"]) for i in range(int(env["GIT_CONFIG_COUNT"]))
    )


def test_create_repo_rejects_option_looking_clone_url(client):
    owner = register_and_login(client, email="urlhard1@zerostrike.dev")
    headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = client.post("/api/v1/projects", json={"name": "P"}, headers=headers).json()
    for bad in ("--upload-pack=touch /tmp/pwn", "file:///etc", "https://u:p@github.com/o/r.git"):
        r = client.post(
            f"/api/v1/projects/{project['id']}/repos",
            json={
                "provider": "github",
                "pat": "ghp_x",
                "organization": "o",
                "repo_full_name": "o/r",
                "clone_url": bad,
                "selected_branch": "main",
            },
            headers=headers,
        )
        assert r.status_code == 422, bad


@pytest.mark.parametrize("bad_url", ["--upload-pack=x", "file:///etc", "/local/path", "https://u:p@example.com/r"])
def test_clone_repo_validates_itself_and_never_runs_git(monkeypatch, tmp_path, bad_url):
    _resolve_to(monkeypatch, "93.184.216.34")
    called = []

    async def fake_run(*a, **kw):
        called.append(a)
        return 0, b"", b""

    monkeypatch.setattr(git_workspace, "_run", fake_run)
    with pytest.raises(GitWorkspaceError):
        asyncio.run(git_workspace.clone_repo(bad_url, "main", str(tmp_path / "wd")))
    assert not called


@pytest.mark.parametrize("ip", ["100.64.0.1", "10.0.0.1", "::ffff:127.0.0.1", "169.254.169.254", "::1"])
def test_validate_repo_url_rejects_non_global(monkeypatch, ip):
    _resolve_to(monkeypatch, ip)
    with pytest.raises(css.CloudScanError):
        css.validate_repo_url("https://example.com/r.git")


def test_validate_repo_url_returns_vetted_ips(monkeypatch):
    _resolve_to(monkeypatch, "93.184.216.34")
    assert css.validate_repo_url("https://example.com/r.git") == ["93.184.216.34"]


def test_clone_repo_env_and_argv_are_hardened(monkeypatch, tmp_path):
    _resolve_to(monkeypatch, "93.184.216.34")
    seen = {}

    async def fake_run(cmd, timeout, env=None, cwd=None):
        seen["cmd"], seen["env"] = cmd, env
        return 0, b"", b""

    monkeypatch.setattr(git_workspace, "_run", fake_run)
    asyncio.run(git_workspace.clone_repo("https://example.com:8443/r.git", "main", str(tmp_path / "wd"), "tok"))
    cfg = _pairs(seen["env"])
    assert cfg["http.followRedirects"] == "false"
    assert cfg["protocol.allow"] == "never"
    assert cfg["http.curloptResolve"] == "example.com:8443:93.184.216.34"
    assert "http.extraHeader" in cfg
    assert seen["cmd"][-3] == "--"


def test_hardening_entries_bracket_ipv6_and_default_port():
    entries = dict(css.git_hardening_entries("http://example.com/r.git", ["2606:2800::1"]))
    assert entries["http.curloptResolve"] == "example.com:80:[2606:2800::1]"


def test_azure_devops_remote_url_with_bare_username_is_accepted():
    # ADO's remoteUrl always carries the org as a username; rejecting it broke every ADO repo.
    from app.core.repo_url import check_repo_url_syntax

    parsed = check_repo_url_syntax("https://myorg@dev.azure.com/myorg/proj/_git/repo")
    assert parsed.hostname == "dev.azure.com"

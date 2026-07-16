import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.services.cloud_scan_service as css
from app.models.scan import Scan

_FIXTURE = Path(__file__).parent / "fixtures" / "go_report_sample.json"


class _FakeCompleted:
    """Stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode, stdout=b"", stderr=b""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_cloud_scan(repo_url="https://github.com/example/repo"):
    # run_cloud_scan is only ever invoked post-claim, so tests reflect the already-claimed state.
    now = datetime.now(timezone.utc)
    return Scan(
        project_id="cloudproj",
        scan_type="cloud",
        triggered_by="cloud",
        status="running",
        repo_url=repo_url,
        created_at=now,
        updated_at=now,
    )


def _patch_subprocess(monkeypatch, tmp_path, clone_rc=0, scan_rc=1, scan_stdout=None):
    """Route both git-clone and scanner invocations through a fake subprocess.run; keep workdir in tmp."""
    monkeypatch.setattr(css.settings, "clone_workdir_path", str(tmp_path))
    monkeypatch.setattr(css, "validate_repo_url", lambda url: None)  # DNS-independent in tests
    scan_stdout = scan_stdout if scan_stdout is not None else _FIXTURE.read_bytes()

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _FakeCompleted(clone_rc, b"", b"clone stderr")
        return _FakeCompleted(scan_rc, scan_stdout, b"")

    monkeypatch.setattr(css.subprocess, "run", fake_run)


def test_cloud_scan_completes_and_ingests(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        reloaded = await Scan.get(scan.id)

        from app.models.finding import Finding
        from app.models.report import Report

        assert reloaded.status == "completed"
        assert await Finding.find(Finding.scan_id == str(scan.id)).count() == 4
        assert await Report.find(Report.scan_id == str(scan.id)).count() == 1

    asyncio.run(run())


def test_cloud_scan_clone_failure_marks_failed(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path, clone_rc=128)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "failed"
        assert "git clone failed" in reloaded.error_message

    asyncio.run(run())


def test_cloud_scan_transient_clone_error_retries_then_succeeds(client, monkeypatch, tmp_path):
    async def _no_delay(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    monkeypatch.setattr(css.settings, "clone_workdir_path", str(tmp_path))
    monkeypatch.setattr(css, "validate_repo_url", lambda url: None)

    calls = {"clone": 0}

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            calls["clone"] += 1
            if calls["clone"] < 2:
                return _FakeCompleted(128, b"", b"fatal: Connection reset by peer")
            return _FakeCompleted(0, b"", b"")
        return _FakeCompleted(1, _FIXTURE.read_bytes(), b"")

    monkeypatch.setattr(css.subprocess, "run", fake_run)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "completed"
        assert calls["clone"] == 2  # first attempt transient-failed, second succeeded

    asyncio.run(run())


def test_cloud_scan_non_transient_clone_error_does_not_retry(client, monkeypatch, tmp_path):
    calls = {"clone": 0}

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            calls["clone"] += 1
            return _FakeCompleted(128, b"", b"fatal: Authentication failed for repo")
        return _FakeCompleted(1, _FIXTURE.read_bytes(), b"")

    monkeypatch.setattr(css.settings, "clone_workdir_path", str(tmp_path))
    monkeypatch.setattr(css, "validate_repo_url", lambda url: None)
    monkeypatch.setattr(css.subprocess, "run", fake_run)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "failed"
        assert calls["clone"] == 1  # a non-transient failure must not burn retry attempts

    asyncio.run(run())


def test_cloud_scan_scanner_error_marks_failed(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path, scan_rc=3, scan_stdout=b"")

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "failed"
        assert "scanner exited 3" in reloaded.error_message

    asyncio.run(run())


def test_cloud_scan_bad_json_marks_failed(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path, scan_rc=0, scan_stdout=b"not json at all")

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "failed"

    asyncio.run(run())


@pytest.mark.parametrize(
    "bad_url",
    ["file:///etc/passwd", "http://localhost/x.git", "http://127.0.0.1/x", "http://169.254.169.254/x"],
)
def test_ssrf_guard_rejects_dangerous_urls(bad_url):
    with pytest.raises(css.CloudScanError):
        css.validate_repo_url(bad_url)


def test_scanner_binary_missing_gives_actionable_message(client, monkeypatch, tmp_path):
    """A FileNotFoundError for the scanner specifically (not git) is a portal misconfiguration —
    the surfaced message must say so distinctly from a generic 'executable not found'."""
    monkeypatch.setattr(css.settings, "clone_workdir_path", str(tmp_path))
    monkeypatch.setattr(css, "validate_repo_url", lambda url: None)

    def fake_run(cmd, **kwargs):
        if cmd[0] == "git":
            return _FakeCompleted(0, b"", b"")
        raise FileNotFoundError(cmd[0])

    monkeypatch.setattr(css.subprocess, "run", fake_run)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "failed"
        assert "not available on this server" in reloaded.error_message
        assert "contact an administrator" in reloaded.error_message

    asyncio.run(run())


def test_git_missing_gives_generic_message(client, monkeypatch, tmp_path):
    """A FileNotFoundError for git (not the scanner) keeps the plain generic message — only the
    scanner binary is a portal-wide misconfiguration; git missing is a different kind of problem."""
    monkeypatch.setattr(css.settings, "clone_workdir_path", str(tmp_path))
    monkeypatch.setattr(css, "validate_repo_url", lambda url: None)
    monkeypatch.setattr(css.subprocess, "run", lambda cmd, **kwargs: (_ for _ in ()).throw(FileNotFoundError(cmd[0])))

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))
        reloaded = await Scan.get(scan.id)
        assert reloaded.status == "failed"
        assert reloaded.error_message == "executable not found: git"

    asyncio.run(run())


def test_scanner_available_reflects_binary_resolution(monkeypatch):
    monkeypatch.setattr(css.shutil, "which", lambda path: None)
    assert css.scanner_available() is False

    monkeypatch.setattr(css.shutil, "which", lambda path: path)
    assert css.scanner_available() is True


def test_missing_scanner_warns_at_startup(monkeypatch, caplog):
    """The whole point of this check is that it's visible the moment the server boots, not just
    buried in the first failed scan's error_message — verify the warning actually fires."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setattr(css, "scanner_available", lambda: False)
    with caplog.at_level("WARNING", logger="app.main"):
        with TestClient(create_app()):
            pass
    assert any("SCANNER_BINARY_PATH" in r.message for r in caplog.records)


def test_clone_uses_bearer_by_default(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path)
    captured_env = {}

    def fake_run(cmd, env=None, **kwargs):
        if cmd[0] == "git":
            captured_env.update(env or {})
            return _FakeCompleted(0, b"", b"")
        return _FakeCompleted(1, _FIXTURE.read_bytes(), b"")

    monkeypatch.setattr(css.subprocess, "run", fake_run)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id), repo_token="my-token")

    asyncio.run(run())
    assert captured_env["GIT_CONFIG_VALUE_0"] == "AUTHORIZATION: Bearer my-token"


def test_clone_uses_basic_auth_for_azure_devops_scheme(client, monkeypatch, tmp_path):
    """A ProjectRepo-resolved Azure DevOps PAT must clone with Basic auth, not Bearer — mixing the
    two schemes is exactly the class of bug that prompted repo_token_auth_scheme to exist."""
    _patch_subprocess(monkeypatch, tmp_path)
    captured_env = {}

    def fake_run(cmd, env=None, **kwargs):
        if cmd[0] == "git":
            captured_env.update(env or {})
            return _FakeCompleted(0, b"", b"")
        return _FakeCompleted(1, _FIXTURE.read_bytes(), b"")

    monkeypatch.setattr(css.subprocess, "run", fake_run)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id), repo_token="ado-pat", repo_token_auth_scheme="basic")

    asyncio.run(run())
    import base64

    expected = base64.b64encode(b":ado-pat").decode()
    assert captured_env["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: Basic {expected}"


def test_workdir_cleaned_up_after_scan(client, monkeypatch, tmp_path):
    _patch_subprocess(monkeypatch, tmp_path)

    async def run():
        scan = _make_cloud_scan()
        await scan.insert()
        await css.run_cloud_scan(str(scan.id))

    asyncio.run(run())
    # The ephemeral clone dir must not survive the run.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith("zs-clone-")]
    assert leftovers == []

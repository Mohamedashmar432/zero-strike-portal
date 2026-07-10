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
    now = datetime.now(timezone.utc)
    return Scan(
        project_id="cloudproj",
        scan_type="cloud",
        triggered_by="cloud",
        status="pending",
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

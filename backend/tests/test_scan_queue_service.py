import asyncio
from datetime import datetime, timedelta, timezone

import app.services.cloud_scan_service as cloud_scan_service
import app.services.scan_queue_service as scan_queue_service
from app.models.scan import Scan


def _make_queued_scan(created_at, repo_token=None):
    now = datetime.now(timezone.utc)
    return Scan(
        project_id="qproj",
        scan_type="cloud",
        triggered_by="cloud",
        status="queued",
        repo_url="https://github.com/example/repo",
        repo_token=repo_token,
        created_at=created_at,
        updated_at=now,
    )


async def _noop(*args, **kwargs):
    pass


def test_drain_respects_capacity(client, monkeypatch):
    monkeypatch.setattr(cloud_scan_service, "run_cloud_scan", _noop)
    monkeypatch.setattr(scan_queue_service.settings, "max_concurrent_cloud_scans", 1)

    async def run():
        base = datetime.now(timezone.utc)
        s1 = _make_queued_scan(base)
        s2 = _make_queued_scan(base + timedelta(seconds=1))
        await s1.insert()
        await s2.insert()

        await scan_queue_service.drain_queue()
        # Let the spawned run_cloud_scan task (a no-op) finish before asserting.
        await asyncio.sleep(0)

        r1 = await Scan.get(s1.id)
        r2 = await Scan.get(s2.id)
        assert r1.status == "running"
        assert r2.status == "queued"  # capacity=1, only the oldest is claimed

    asyncio.run(run())


def test_drain_claims_fifo_and_clears_token(client, monkeypatch):
    captured = {}

    async def fake_run(scan_id, repo_token=None):
        captured["scan_id"] = scan_id
        captured["repo_token"] = repo_token

    monkeypatch.setattr(cloud_scan_service, "run_cloud_scan", fake_run)
    monkeypatch.setattr(scan_queue_service.settings, "max_concurrent_cloud_scans", 1)

    async def run():
        base = datetime.now(timezone.utc)
        older = _make_queued_scan(base, repo_token="secret-older")
        newer = _make_queued_scan(base + timedelta(seconds=5), repo_token="secret-newer")
        await newer.insert()
        await older.insert()

        await scan_queue_service.drain_queue()
        await asyncio.sleep(0)

        assert captured["scan_id"] == str(older.id)
        assert captured["repo_token"] == "secret-older"

        reloaded = await Scan.get(older.id)
        assert reloaded.status == "running"
        assert reloaded.repo_token is None  # cleared atomically at claim time

    asyncio.run(run())


def test_drain_noop_when_no_capacity(client, monkeypatch):
    monkeypatch.setattr(scan_queue_service.settings, "max_concurrent_cloud_scans", 1)

    async def run():
        now = datetime.now(timezone.utc)
        running = Scan(
            project_id="qproj",
            scan_type="cloud",
            triggered_by="cloud",
            status="running",
            repo_url="https://github.com/example/repo",
            created_at=now,
            updated_at=now,
        )
        await running.insert()
        queued = _make_queued_scan(now)
        await queued.insert()

        await scan_queue_service.drain_queue()

        reloaded = await Scan.get(queued.id)
        assert reloaded.status == "queued"  # no free capacity, left untouched

    asyncio.run(run())


def test_concurrent_drain_claims_each_scan_once(client, monkeypatch):
    monkeypatch.setattr(cloud_scan_service, "run_cloud_scan", _noop)
    monkeypatch.setattr(scan_queue_service.settings, "max_concurrent_cloud_scans", 1)

    async def run():
        base = datetime.now(timezone.utc)
        s1 = _make_queued_scan(base)
        s2 = _make_queued_scan(base + timedelta(seconds=1))
        await s1.insert()
        await s2.insert()

        await asyncio.gather(scan_queue_service.drain_queue(), scan_queue_service.drain_queue())
        await asyncio.sleep(0)

        statuses = sorted([(await Scan.get(s1.id)).status, (await Scan.get(s2.id)).status])
        # capacity=1 across both concurrent calls together — exactly one claimed, not both.
        assert statuses == ["queued", "running"]

    asyncio.run(run())


def test_reap_stuck_scans_marks_stale_running_failed(client, monkeypatch):
    monkeypatch.setattr(scan_queue_service.settings, "scan_timeout_seconds", 10)
    monkeypatch.setattr(scan_queue_service.settings, "queue_stuck_multiplier", 3)

    async def run():
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
        fresh_time = datetime.now(timezone.utc)
        stale = Scan(
            project_id="qproj",
            scan_type="cloud",
            triggered_by="cloud",
            status="running",
            repo_url="https://github.com/example/repo",
            created_at=stale_time,
            updated_at=stale_time,
        )
        fresh = Scan(
            project_id="qproj",
            scan_type="cloud",
            triggered_by="cloud",
            status="running",
            repo_url="https://github.com/example/repo",
            created_at=fresh_time,
            updated_at=fresh_time,
        )
        await stale.insert()
        await fresh.insert()

        await scan_queue_service.reap_stuck_scans()

        assert (await Scan.get(stale.id)).status == "failed"
        assert (await Scan.get(fresh.id)).status == "running"

    asyncio.run(run())

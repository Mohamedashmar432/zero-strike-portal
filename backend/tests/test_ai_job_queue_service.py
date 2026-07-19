import asyncio
from datetime import datetime, timedelta, timezone

import app.services.ai_analysis_service as ai_analysis_service
import app.services.ai_job_queue_service as ai_job_queue_service
from app.models.ai_analysis_job import AIAnalysisJob


def _make_queued_job(created_at, scope_key="fp-1", kind="finding"):
    now = datetime.now(timezone.utc)
    return AIAnalysisJob(
        kind=kind,
        project_id="qproj",
        scan_id="scan-1",
        fingerprint=scope_key if kind == "finding" else None,
        scope_key=scope_key,
        status="queued",
        created_at=created_at,
        updated_at=now,
    )


async def _noop(*args, **kwargs):
    pass


def test_drain_respects_capacity(client, monkeypatch):
    monkeypatch.setattr(ai_analysis_service, "run_job", _noop)
    monkeypatch.setattr(ai_job_queue_service.settings, "max_concurrent_ai_jobs", 1)

    async def run():
        base = datetime.now(timezone.utc)
        j1 = _make_queued_job(base, scope_key="fp-1")
        j2 = _make_queued_job(base + timedelta(seconds=1), scope_key="fp-2")
        await j1.insert()
        await j2.insert()

        await ai_job_queue_service.drain_queue()
        await asyncio.sleep(0)

        r1 = await AIAnalysisJob.get(j1.id)
        r2 = await AIAnalysisJob.get(j2.id)
        assert r1.status == "running"
        assert r2.status == "queued"  # capacity=1, only the oldest is claimed

    asyncio.run(run())


def test_drain_claims_oldest_queued_first(client, monkeypatch):
    captured = {}

    async def fake_run(job):
        captured["job_id"] = str(job.id)

    monkeypatch.setattr(ai_analysis_service, "run_job", fake_run)
    monkeypatch.setattr(ai_job_queue_service.settings, "max_concurrent_ai_jobs", 1)

    async def run():
        base = datetime.now(timezone.utc)
        older = _make_queued_job(base, scope_key="fp-old")
        newer = _make_queued_job(base + timedelta(seconds=5), scope_key="fp-new")
        await newer.insert()
        await older.insert()

        await ai_job_queue_service.drain_queue()
        await asyncio.sleep(0)

        assert captured["job_id"] == str(older.id)
        reloaded = await AIAnalysisJob.get(older.id)
        assert reloaded.status == "running"

    asyncio.run(run())


def test_drain_noop_when_no_capacity(client, monkeypatch):
    monkeypatch.setattr(ai_job_queue_service.settings, "max_concurrent_ai_jobs", 1)

    async def run():
        now = datetime.now(timezone.utc)
        running = _make_queued_job(now, scope_key="fp-running")
        running.status = "running"
        await running.insert()
        queued = _make_queued_job(now, scope_key="fp-queued")
        await queued.insert()

        await ai_job_queue_service.drain_queue()

        reloaded = await AIAnalysisJob.get(queued.id)
        assert reloaded.status == "queued"  # no free capacity, left untouched

    asyncio.run(run())


def test_concurrent_drain_claims_each_job_once(client, monkeypatch):
    monkeypatch.setattr(ai_analysis_service, "run_job", _noop)
    monkeypatch.setattr(ai_job_queue_service.settings, "max_concurrent_ai_jobs", 1)

    async def run():
        base = datetime.now(timezone.utc)
        j1 = _make_queued_job(base, scope_key="fp-1")
        j2 = _make_queued_job(base + timedelta(seconds=1), scope_key="fp-2")
        await j1.insert()
        await j2.insert()

        await asyncio.gather(ai_job_queue_service.drain_queue(), ai_job_queue_service.drain_queue())
        await asyncio.sleep(0)

        statuses = sorted([(await AIAnalysisJob.get(j1.id)).status, (await AIAnalysisJob.get(j2.id)).status])
        # capacity=1 across both concurrent calls together -- exactly one claimed, not both.
        assert statuses == ["queued", "running"]

    asyncio.run(run())


def test_reap_stuck_ai_jobs_marks_stale_running_failed(client, monkeypatch):
    monkeypatch.setattr(ai_job_queue_service.settings, "ai_job_timeout_seconds", 10)
    monkeypatch.setattr(ai_job_queue_service.settings, "ai_queue_stuck_multiplier", 3)

    async def run():
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
        fresh_time = datetime.now(timezone.utc)
        stale = _make_queued_job(stale_time, scope_key="fp-stale")
        stale.status = "running"
        stale.updated_at = stale_time
        stale.max_attempts = 1  # no retry budget -- one reap should terminally fail it
        fresh = _make_queued_job(fresh_time, scope_key="fp-fresh")
        fresh.status = "running"
        fresh.updated_at = fresh_time
        await stale.insert()
        await fresh.insert()

        await ai_job_queue_service.reap_stuck_ai_jobs()

        assert (await AIAnalysisJob.get(stale.id)).status == "failed"
        assert (await AIAnalysisJob.get(fresh.id)).status == "running"

    asyncio.run(run())


def test_reap_stuck_ai_job_with_retry_budget_requeues_then_dead_letters(client, monkeypatch):
    monkeypatch.setattr(ai_job_queue_service.settings, "ai_job_timeout_seconds", 10)
    monkeypatch.setattr(ai_job_queue_service.settings, "ai_queue_stuck_multiplier", 3)

    async def run():
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=1000)
        job = _make_queued_job(stale_time, scope_key="fp-retry")
        job.status = "running"
        job.updated_at = stale_time
        job.max_attempts = 2
        await job.insert()

        # First reap: retry budget remains (retry_count 0 + 1 < max_attempts 2) -> requeued.
        await ai_job_queue_service.reap_stuck_ai_jobs()
        reloaded = await AIAnalysisJob.get(job.id)
        assert reloaded.status == "queued"
        assert reloaded.retry_count == 1

        # Simulate it getting claimed again and going stale a second time.
        reloaded.status = "running"
        reloaded.updated_at = stale_time
        await reloaded.save()

        # Second reap: retry budget exhausted (1 + 1 is not < 2) -> terminal, dead-lettered.
        await ai_job_queue_service.reap_stuck_ai_jobs()
        final = await AIAnalysisJob.get(job.id)
        assert final.status == "failed"
        assert "retries exhausted" in final.error_message

    asyncio.run(run())

"""Queue mechanics for compliance audits — mirrors tests/test_ai_job_queue_service.py.

These cover the crash-recovery behaviour the API tests can't reach: an audit whose
worker died mid-run must be requeued (or dead-lettered), not left "running" forever.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import app.services.compliance_audit_service as compliance_audit_service
import app.services.compliance_queue_service as compliance_queue_service
from app.models.compliance_audit import ComplianceAudit


def _make_audit(created_at, *, status="queued", updated_at=None, retry_count=0, max_attempts=2):
    now = datetime.now(timezone.utc)
    return ComplianceAudit(
        project_id="qproj",
        frameworks=["soc2"],
        scope="latest",
        depth="deterministic",
        status=status,
        retry_count=retry_count,
        max_attempts=max_attempts,
        created_at=created_at,
        updated_at=updated_at or now,
    )


async def _noop(*args, **kwargs):
    pass


def test_drain_respects_capacity(client, monkeypatch):
    monkeypatch.setattr(compliance_audit_service, "run_job", _noop)
    monkeypatch.setattr(compliance_queue_service.settings, "max_concurrent_compliance_audits", 1)

    async def run():
        base = datetime.now(timezone.utc)
        first = _make_audit(base)
        second = _make_audit(base + timedelta(seconds=1))
        await first.insert()
        await second.insert()

        await compliance_queue_service.drain_queue()
        await asyncio.sleep(0)

        assert (await ComplianceAudit.get(first.id)).status == "running"
        assert (await ComplianceAudit.get(second.id)).status == "queued"

    asyncio.run(run())


def test_drain_claims_oldest_first(client, monkeypatch):
    captured = {}

    async def fake_run(audit):
        captured["id"] = str(audit.id)

    monkeypatch.setattr(compliance_audit_service, "run_job", fake_run)
    monkeypatch.setattr(compliance_queue_service.settings, "max_concurrent_compliance_audits", 1)

    async def run():
        base = datetime.now(timezone.utc)
        newer = _make_audit(base + timedelta(seconds=10))
        older = _make_audit(base)
        await newer.insert()  # inserted first, but created later
        await older.insert()

        await compliance_queue_service.drain_queue()
        await asyncio.sleep(0)
        assert captured["id"] == str(older.id)

    asyncio.run(run())


def test_concurrent_drains_claim_an_audit_only_once(client, monkeypatch):
    """Two backend replicas draining at the same moment must not both run one audit."""
    runs = []

    async def fake_run(audit):
        runs.append(str(audit.id))

    monkeypatch.setattr(compliance_audit_service, "run_job", fake_run)
    monkeypatch.setattr(compliance_queue_service.settings, "max_concurrent_compliance_audits", 4)

    async def run():
        audit = _make_audit(datetime.now(timezone.utc))
        await audit.insert()

        await asyncio.gather(
            compliance_queue_service.drain_queue(),
            compliance_queue_service.drain_queue(),
        )
        await asyncio.sleep(0)
        assert runs == [str(audit.id)]

    asyncio.run(run())


def test_drain_is_a_noop_when_nothing_is_queued(client, monkeypatch):
    monkeypatch.setattr(compliance_audit_service, "run_job", _noop)

    async def run():
        await compliance_queue_service.drain_queue()  # must not raise
        assert await ComplianceAudit.find().count() == 0

    asyncio.run(run())


def test_reap_requeues_a_stranded_audit_while_retries_remain(client, monkeypatch):
    monkeypatch.setattr(compliance_queue_service.settings, "compliance_audit_timeout_seconds", 1)
    monkeypatch.setattr(compliance_queue_service.settings, "compliance_queue_stuck_multiplier", 1)

    async def run():
        stale = datetime.now(timezone.utc) - timedelta(hours=1)
        audit = _make_audit(stale, status="running", updated_at=stale, max_attempts=2)
        await audit.insert()

        await compliance_queue_service.reap_stuck_audits()

        reaped = await ComplianceAudit.get(audit.id)
        assert reaped.status == "queued"
        assert reaped.retry_count == 1
        assert reaped.started_at is None

    asyncio.run(run())


def test_reap_dead_letters_once_retries_are_exhausted(client, monkeypatch):
    monkeypatch.setattr(compliance_queue_service.settings, "compliance_audit_timeout_seconds", 1)
    monkeypatch.setattr(compliance_queue_service.settings, "compliance_queue_stuck_multiplier", 1)

    async def run():
        stale = datetime.now(timezone.utc) - timedelta(hours=1)
        audit = _make_audit(stale, status="running", updated_at=stale, retry_count=1, max_attempts=2)
        await audit.insert()

        await compliance_queue_service.reap_stuck_audits()

        reaped = await ComplianceAudit.get(audit.id)
        assert reaped.status == "failed"
        assert "retries exhausted" in reaped.error_message
        assert reaped.completed_at is not None

    asyncio.run(run())


def test_reap_leaves_a_freshly_running_audit_alone(client, monkeypatch):
    monkeypatch.setattr(compliance_queue_service.settings, "compliance_audit_timeout_seconds", 300)
    monkeypatch.setattr(compliance_queue_service.settings, "compliance_queue_stuck_multiplier", 3)

    async def run():
        audit = _make_audit(datetime.now(timezone.utc), status="running")
        await audit.insert()

        await compliance_queue_service.reap_stuck_audits()
        assert (await ComplianceAudit.get(audit.id)).status == "running"

    asyncio.run(run())


def test_a_crashed_worker_task_is_logged_and_not_reraised(client, monkeypatch):
    """drain_queue fires run_job as a detached task. If that task dies, the done-callback
    must log it rather than surface an "exception was never retrieved" warning — and must
    not itself blow up on a cancelled task."""

    async def crash(audit):
        raise RuntimeError("worker died")

    monkeypatch.setattr(compliance_audit_service, "run_job", crash)

    async def run():
        audit = _make_audit(datetime.now(timezone.utc))
        await audit.insert()
        await compliance_queue_service.drain_queue()
        await asyncio.sleep(0.05)
        # The callback ran, logged, and dropped the task from the in-flight set.
        assert not compliance_queue_service._in_flight

        cancelled = asyncio.create_task(asyncio.sleep(10))
        cancelled.cancel()
        try:
            await cancelled
        except asyncio.CancelledError:
            pass
        compliance_queue_service._log_if_failed(cancelled)  # must not raise

    asyncio.run(run())


def test_a_healthy_poll_tick_reaps_then_drains(client, monkeypatch):
    order = []

    async def fake_reap():
        order.append("reap")

    async def fake_drain():
        order.append("drain")

    monkeypatch.setattr(compliance_queue_service, "reap_stuck_audits", fake_reap)
    monkeypatch.setattr(compliance_queue_service, "drain_queue", fake_drain)
    monkeypatch.setattr(compliance_queue_service.settings, "queue_poll_interval_seconds", 0)

    async def run():
        task = asyncio.create_task(compliance_queue_service.poll_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert order[:2] == ["reap", "drain"]

    asyncio.run(run())


def test_poll_tick_survives_a_failing_reap(client, monkeypatch):
    """The poll loop must never die on one bad tick — it's the only crash-recovery path."""
    calls = {"drain": 0}

    async def boom():
        raise RuntimeError("mongo blip")

    async def fake_drain():
        calls["drain"] += 1

    monkeypatch.setattr(compliance_queue_service, "reap_stuck_audits", boom)
    monkeypatch.setattr(compliance_queue_service, "drain_queue", fake_drain)
    monkeypatch.setattr(compliance_queue_service.settings, "queue_poll_interval_seconds", 0)

    async def run():
        task = asyncio.create_task(compliance_queue_service.poll_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        # It kept ticking despite reap raising every time, and never reached drain.
        assert calls["drain"] == 0

    asyncio.run(run())

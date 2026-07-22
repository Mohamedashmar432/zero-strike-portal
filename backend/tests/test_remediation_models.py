"""AI Auto-Fix (remediation) model + queue smoke tests (mongomock).

Guards the RemediationJob/AIFixProposal registration and the atomic claim + crash-recovery
reap that ai_remediation_queue_service relies on. Mirrors test_ai_insight_models.py's shape.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.services import ai_remediation_queue_service


def test_remediation_job_round_trips(client):
    async def run():
        job = RemediationJob(
            kind="propose",
            project_id="proj-1",
            scan_id="scan-1",
            finding_ids=["f-1", "f-2"],
            scope_key="scan-1:propose:abc",
            trace_id="trace-1",
        )
        await job.insert()
        reloaded = await RemediationJob.find_one(RemediationJob.scope_key == "scan-1:propose:abc")
        assert reloaded is not None
        assert reloaded.status == "queued"
        assert reloaded.max_attempts == 2
        assert reloaded.finding_ids == ["f-1", "f-2"]
        assert reloaded.proposal_id is None

    asyncio.run(run())


def test_ai_fix_proposal_lifecycle_fields_round_trip(client):
    async def run():
        doc = AIFixProposal(
            finding_id="f-1",
            scan_id="scan-1",
            project_id="proj-1",
            can_fix=True,
            confidence_score=91.0,
            file_path="src/app.py",
            review_state="pr_open",
            branch_name="zerostrike/fix-abc",
            pr_url="https://github.com/o/r/pull/7",
            pr_number=7,
            validation={"scope_ok": True, "target_cleared": True, "new_finding_count": 0},
        )
        await doc.insert()
        reloaded = await AIFixProposal.find_one(AIFixProposal.finding_id == "f-1")
        assert reloaded is not None
        assert reloaded.review_state == "pr_open"
        assert reloaded.status == "proposed"  # coarse status untouched
        assert reloaded.validation["target_cleared"] is True
        assert reloaded.pr_number == 7

    asyncio.run(run())


def test_claim_next_takes_oldest_and_flips_to_running(client):
    async def run():
        older = RemediationJob(
            kind="propose", project_id="p", scan_id="s", scope_key="s:propose:1", trace_id="t1",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        newer = RemediationJob(
            kind="propose", project_id="p", scan_id="s", scope_key="s:propose:2", trace_id="t2",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
        await newer.insert()
        await older.insert()

        claimed = await ai_remediation_queue_service._claim_next()
        assert claimed is not None and claimed.scope_key == "s:propose:1"
        # The claimed doc is flipped to running in the DB (BEFORE-image returned, so re-read).
        running = await RemediationJob.find_one(RemediationJob.scope_key == "s:propose:1")
        assert running.status == "running"

        second = await ai_remediation_queue_service._claim_next()
        assert second is not None and second.scope_key == "s:propose:2"
        assert await ai_remediation_queue_service._claim_next() is None  # nothing left queued

    asyncio.run(run())


def test_reap_requeues_then_dead_letters(client):
    async def run():
        stuck_after = timedelta(
            seconds=settings.remediation_job_timeout_seconds * settings.remediation_queue_stuck_multiplier
        )
        old = datetime.now(timezone.utc) - stuck_after - timedelta(seconds=60)

        # apply jobs have max_attempts=1 -> a stuck one dead-letters immediately (writes never retry).
        apply_job = RemediationJob(
            kind="apply", project_id="p", scan_id="s", proposal_id="prop-1",
            scope_key="s:apply:prop-1", trace_id="t", status="running", max_attempts=1,
        )
        await apply_job.insert()
        apply_job.updated_at = old
        await apply_job.save()

        await ai_remediation_queue_service.reap_stuck_remediation_jobs()
        reaped = await RemediationJob.find_one(RemediationJob.scope_key == "s:apply:prop-1")
        assert reaped.status == "failed"
        assert reaped.error_message

        # propose jobs have max_attempts=2 -> a stuck one requeues (retry budget left).
        propose_job = RemediationJob(
            kind="propose", project_id="p", scan_id="s", scope_key="s:propose:x",
            trace_id="t", status="running", max_attempts=2,
        )
        await propose_job.insert()
        propose_job.updated_at = old
        await propose_job.save()

        await ai_remediation_queue_service.reap_stuck_remediation_jobs()
        requeued = await RemediationJob.find_one(RemediationJob.scope_key == "s:propose:x")
        assert requeued.status == "queued"
        assert requeued.retry_count == 1

    asyncio.run(run())

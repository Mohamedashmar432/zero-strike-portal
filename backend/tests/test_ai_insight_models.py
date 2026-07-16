"""Smoke check for the AI-insight/fix-proposal collection skeletons (see
docs/ARCHITECTURE_REVIEW_AND_AI_ROADMAP.md): confirms they're registered with Beanie
and round-trip through Mongo. No service writes to these yet -- this just guards
against the registration wiring in db/mongo.py silently breaking.
"""

import asyncio

from app.models.ai_finding_insight import AIFindingInsight
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_scan_insight import AIScanInsight


def test_ai_finding_insight_round_trips(client):
    async def run():
        doc = AIFindingInsight(fingerprint="fp-1", project_id="proj-1", owasp=["A03:2021"])
        await doc.insert()
        reloaded = await AIFindingInsight.find_one(
            AIFindingInsight.fingerprint == "fp-1", AIFindingInsight.project_id == "proj-1"
        )
        assert reloaded is not None
        assert reloaded.is_false_positive is None
        assert reloaded.owasp == ["A03:2021"]

    asyncio.run(run())


def test_ai_scan_insight_round_trips(client):
    async def run():
        doc = AIScanInsight(scan_id="scan-1", project_id="proj-1", total_findings_analyzed=5)
        await doc.insert()
        reloaded = await AIScanInsight.find_one(AIScanInsight.scan_id == "scan-1")
        assert reloaded is not None
        assert reloaded.false_positive_count == 0

    asyncio.run(run())


def test_ai_fix_proposal_round_trips(client):
    async def run():
        doc = AIFixProposal(
            finding_id="finding-1", scan_id="scan-1", project_id="proj-1",
            can_fix=True, confidence_score=92.0,
        )
        await doc.insert()
        reloaded = await AIFixProposal.find_one(AIFixProposal.finding_id == "finding-1")
        assert reloaded is not None
        assert reloaded.status == "proposed"
        assert reloaded.confidence_score == 92.0

    asyncio.run(run())

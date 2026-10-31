import asyncio

from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_usage_event import AIUsageEvent
from app.services import ai_quality_service


def test_autofix_quality_rates(client):
    async def run():
        base = dict(scan_id="s", project_id="p")
        await AIFixProposal(finding_id="F1", can_fix=True, review_state="pr_open", pr_state="merged",
                            critique={"verdict": "pass"}, validation={"target_cleared": True}, **base).insert()
        await AIFixProposal(finding_id="F2", can_fix=True, review_state="dismissed",
                            critique={"verdict": "reject"}, validation={"target_cleared": False}, **base).insert()
        await AIFixProposal(finding_id="F3", can_fix=False, critique={"skipped": "no_patch"}, **base).insert()
        # A critic reject turns can_fix off -- it must still be counted as a reject.
        await AIFixProposal(finding_id="F4", can_fix=False, critique={"verdict": "Reject"}, **base).insert()
        # A re-scan disabled by config is neither cleared nor failed.
        await AIFixProposal(finding_id="F5", can_fix=True, review_state="proposed",
                            validation={"skipped": True}, **base).insert()
        for feature, tokens, cached in (("autofix", 1000, 0), ("autofix", 1500, 900), ("critic", 500, 0)):
            await AIUsageEvent(provider="anthropic", feature=feature, project_id="p", finding_id="F1",
                               prompt_tokens=tokens, cached_prompt_tokens=cached, cost_usd=0.01).insert()
        await AIUsageEvent(provider="anthropic", feature="analysis", project_id="p", prompt_tokens=99).insert()

        q = await ai_quality_service.autofix_quality(project_id=None, days=30)
        assert q["proposals"] == 5 and q["drafted"] == 3
        assert q["acceptance_rate"] == 0.333
        assert q["dismissal_rate"] == 0.333
        assert q["rescan_cleared_rate"] == 0.5
        assert q["merged"] == 1
        assert q["critic_verdicts"] == {"pass": 1, "reject": 2, "skipped": 1}
        assert q["avg_calls_per_finding"] == 3.0
        assert q["avg_tokens_per_finding"] == 3000.0
        assert q["cache_hit_rate"] == 0.3  # 900 cached of 3000 prompt tokens

        assert (await ai_quality_service.autofix_quality(project_id="other", days=30))["proposals"] == 0

    asyncio.run(run())

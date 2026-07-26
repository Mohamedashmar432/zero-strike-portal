"""A raw provider exception (internals, org ids, nested JSON -- as observed live from Groq) must
never reach the user-facing proposal.explanation/manual_review_reason. Covers the mapping
(_user_facing_failure_message) and the end-to-end propose flow when the agent raises."""

import asyncio

from app.services import llm_client
from app.services.ai_remediation_service import _user_facing_failure_message


def test_maps_each_llm_error_type_to_a_clean_message_with_no_raw_internals():
    raw = 'GroqException - {"error":{"message":"...","code":"rate_limit_exceeded", "org": "org_secret_123"}}'

    msg = _user_facing_failure_message(llm_client.LLMTransientError(raw))
    assert raw not in msg and "org_secret_123" not in msg
    assert "rate-limited" in msg or "unavailable" in msg

    msg = _user_facing_failure_message(llm_client.LLMPermanentError(raw))
    assert raw not in msg and "org_secret_123" not in msg

    msg = _user_facing_failure_message(llm_client.LLMMalformedResponseError(raw))
    assert raw not in msg

    msg = _user_facing_failure_message(llm_client.LLMNotConfiguredError(raw))
    assert raw not in msg and "Settings" in msg

    msg = _user_facing_failure_message(asyncio.TimeoutError())
    assert "timed out" in msg


def test_propose_run_job_never_leaks_raw_exception_text(client, monkeypatch):
    import app.services.ai_remediation_agent as ai_remediation_agent
    from app.core import security
    from app.models.ai_fix_proposal import AIFixProposal
    from app.models.ai_provider_config import AIProviderConfig
    from app.models.ai_remediation_job import RemediationJob
    from app.models.finding import Finding, LocationEmbedded
    from app.services import ai_remediation_service

    raw_secret = "GroqException - org_01kf198j7qerbarbkm12z0a6np rate_limit_exceeded"

    async def fake_run_agent(issue_bundle, ctx, budgets, revision_note=None):
        raise llm_client.LLMTransientError(raw_secret)

    monkeypatch.setattr(ai_remediation_agent, "run_agent", fake_run_agent)

    async def run():
        await AIProviderConfig(
            name="Test", provider="groq", model_name="openai/gpt-oss-120b", is_active=True,
            api_key_encrypted=security.encrypt_secret("test-key"),
        ).insert()
        finding = Finding(
            scan_id="s", project_id="p", fingerprint="fp-leak", rule_name="Test Rule",
            message="m", location=LocationEmbedded(file="a.py", start_line=1), severity="high",
        )
        await finding.insert()
        job = RemediationJob(
            kind="propose", project_id="p", scan_id="s", finding_ids=[str(finding.id)],
            scope_key="s:propose:leak", trace_id="t",
        )
        await job.insert()
        await ai_remediation_service.run_job(job)
        return finding

    finding = asyncio.run(run())

    async def _check():
        return await AIFixProposal.find_one(AIFixProposal.finding_id == str(finding.id))

    proposal = asyncio.run(_check())
    assert proposal is not None
    assert raw_secret not in (proposal.explanation or "")
    assert raw_secret not in (proposal.manual_review_reason or "")
    assert proposal.review_state == "manual_review"

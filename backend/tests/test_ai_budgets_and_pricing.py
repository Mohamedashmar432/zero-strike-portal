"""AI cost accuracy and per-project budgets (docs/AI_PRICING_AND_BUDGETS.md).

The guarantees: an unpriceable call is recorded as unknown, never as free; a provider's own price
override wins; a stale or failed price download never replaces newer prices; each budget threshold
emails the project owner exactly once a month; a hard stop refuses before any provider is billed.
"""

import asyncio
from datetime import datetime, timezone

import litellm
import pytest

import app.services.llm_client as llm_client
from app.models.ai_usage_event import AIUsageEvent
from app.models.project import Project
from app.services import ai_analytics_service, ai_budget_service, ai_provider_config_service, pricing_service
from tests.test_auth_flow import register_and_login
from tests.test_byok_ai_gates import _create_project, _headers
from tests.test_llm_client import _FakeResponse, _FakeUsage


def _fake_llm(monkeypatch, *, cost=None, prompt=1000, completion=2000):
    calls: list[str] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs["model"])
        return _FakeResponse('{"ok": true}', usage=_FakeUsage(prompt, completion))

    def fake_cost(**_):
        if cost is None:
            raise ValueError("model not in the price map")
        return cost

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(litellm, "completion_cost", fake_cost)
    return calls


async def _config(**pricing):
    return await ai_provider_config_service.create_config(
        name="P", provider="openai", model_name="some-new-model", base_url=None, temperature=0.0,
        api_key="sk-test", created_by=None, **pricing,
    )


async def _project(**budget):
    now = datetime.now(timezone.utc)
    return await Project(name="Budgeted", owner_id="owner-1", created_at=now, updated_at=now, **budget).insert()


async def _spend(project_id: str, cost: float, tokens: int = 0):
    await ai_provider_config_service.record_usage(
        str((await _config()).id), success=True, cost_usd=cost, prompt_tokens=tokens, project_id=project_id
    )


def _capture_notify(monkeypatch):
    sent: list[dict] = []

    async def fake_notify(event_key, **kwargs):
        sent.append({"event": event_key, **kwargs})
        return 1

    monkeypatch.setattr(ai_budget_service.notification_service, "notify", fake_notify)
    return sent


# --- pricing -----------------------------------------------------------------------------------


def test_unpriceable_call_is_recorded_as_unknown_not_free(client, monkeypatch):
    _fake_llm(monkeypatch, cost=None)

    async def run():
        await _config()
        await llm_client.get_completion([{"role": "user", "content": "hi"}])
        event = await AIUsageEvent.find_one()
        assert event.cost_known is False and event.cost_usd == 0.0
        assert event.prompt_tokens == 1000  # tokens still come from the provider either way
        totals = (await ai_analytics_service.get_analytics(project_id=None))["totals"]
        assert totals["unpriced"] == 1

    asyncio.run(run())


def test_price_override_wins_over_the_price_map(client, monkeypatch):
    _fake_llm(monkeypatch, cost=99.0)

    async def run():
        await _config(input_cost_per_million=3.0, output_cost_per_million=15.0)
        await llm_client.get_completion([{"role": "user", "content": "hi"}])
        event = await AIUsageEvent.find_one()
        assert event.cost_known is True
        assert event.cost_usd == pytest.approx(1000 * 3 / 1e6 + 2000 * 15 / 1e6)

    asyncio.run(run())


def test_refresh_merges_only_a_live_download(monkeypatch):
    entry = {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}
    monkeypatch.setattr(litellm, "get_model_cost_map", lambda url: {"zz-brand-new-model": entry})
    try:
        monkeypatch.setattr(pricing_service, "get_model_cost_map_source_info", lambda: {"source": "local"})
        status = asyncio.run(pricing_service.refresh())
        assert "zz-brand-new-model" not in litellm.model_cost  # a bundled fallback never overwrites
        assert status["fallback_reason"]

        monkeypatch.setattr(pricing_service, "get_model_cost_map_source_info", lambda: {"source": "remote"})
        status = asyncio.run(pricing_service.refresh())
        assert litellm.model_cost["zz-brand-new-model"] == entry
        assert status["source"] == "remote" and status["fallback_reason"] is None
    finally:
        litellm.model_cost.pop("zz-brand-new-model", None)


# --- budgets -----------------------------------------------------------------------------------


def test_each_threshold_emails_the_owner_once(client, monkeypatch):
    sent = _capture_notify(monkeypatch)

    async def run():
        project = await _project(ai_budget_usd_monthly=1.0, ai_budget_alert_percent=80)
        pid = str(project.id)
        await _spend(pid, 0.85)  # 85% -> the 80% alert
        await _spend(pid, 0.01)  # still under 100% -> nothing new
        await _spend(pid, 0.20)  # 106% -> the limit alert
        await _spend(pid, 0.20)  # already alerted at 100% this month
        return pid

    pid = asyncio.run(run())
    assert [s["severity"] for s in sent] == ["warning", "error"]
    assert all(s["event"] == "ai.budget_threshold" and s["only_user_ids"] == ["owner-1"] for s in sent)
    assert all(s["project_id"] == pid for s in sent)


def test_token_limit_alerts_independently_of_spend(client, monkeypatch):
    sent = _capture_notify(monkeypatch)

    async def run():
        project = await _project(ai_budget_tokens_monthly=1000)
        await _spend(str(project.id), 0.0, tokens=1200)

    asyncio.run(run())
    assert len(sent) == 1 and "token" in sent[0]["title"]


def test_hard_stop_refuses_before_any_provider_is_called(client, monkeypatch):
    calls = _fake_llm(monkeypatch, cost=0.01)

    async def run():
        project = await _project(ai_budget_usd_monthly=0.5, ai_budget_hard_stop=True)
        await _spend(str(project.id), 0.6)
        with pytest.raises(llm_client.LLMPermanentError, match="monthly AI budget"):
            await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=str(project.id))

    asyncio.run(run())
    assert calls == []


def test_over_budget_without_hard_stop_still_runs(client, monkeypatch):
    calls = _fake_llm(monkeypatch, cost=0.01)

    async def run():
        project = await _project(ai_budget_usd_monthly=0.5)
        await _spend(str(project.id), 0.6)
        await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=str(project.id))

    asyncio.run(run())
    assert len(calls) == 1


def test_budget_endpoints_gate_on_role_and_rearm_alerts(client, monkeypatch):
    _capture_notify(monkeypatch)
    owner = _headers(register_and_login(client, "budget-owner@example.com"))
    outsider = _headers(register_and_login(client, "budget-outsider@example.com"))
    project = _create_project(client, owner, name="Budget Demo")
    url = f"/api/v1/projects/{project['id']}/ai-budget"

    r = client.get(url, headers=owner)
    assert r.status_code == 200
    assert r.json()["usd_monthly"] is None and r.json()["alert_percent"] == 80

    assert client.get(url, headers=outsider).status_code == 403
    body = {"usd_monthly": 50, "tokens_monthly": None, "alert_percent": 75, "hard_stop": True}
    assert client.put(url, json=body, headers=outsider).status_code == 403

    async def mark_alerted():
        p = await Project.get(project["id"])
        p.ai_budget_alerts_sent = ["2026-10:usd:75"]
        await p.save()

    asyncio.run(mark_alerted())
    r = client.put(url, json=body, headers=owner)
    assert r.status_code == 200
    assert r.json()["usd_monthly"] == 50 and r.json()["hard_stop"] is True
    assert asyncio.run(Project.get(project["id"])).ai_budget_alerts_sent == []

    assert client.put(url, json={**body, "alert_percent": 100}, headers=owner).status_code == 422

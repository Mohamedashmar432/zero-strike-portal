"""Provider resolution under Project BYOK.

The guarantee being protected: with BYOK on, a project's calls run on that project's key and
nothing else. Not the portal's key, not another project's -- not even when the project's own
provider is failing, because falling back would silently bill the portal for a project's work.
"""

import asyncio

import litellm
import pytest

import app.services.llm_client as llm_client
from app.models.ai_usage_event import AIUsageEvent
from app.services import ai_provider_config_service
from tests.test_llm_client import _FakeResponse, _FakeUsage, _no_delay

PROJECT_A = "aaaaaaaaaaaaaaaaaaaaaaaa"


async def _config(*, name, api_key, project_id=None, model_name="gpt-4o"):
    return await ai_provider_config_service.create_config(
        name=name,
        provider="openai",
        model_name=model_name,
        base_url=None,
        temperature=0.0,
        api_key=api_key,
        created_by=None,
        project_id=project_id,
    )


def _record_keys(monkeypatch):
    """Captures the api_key litellm was actually called with -- the only unambiguous evidence of
    which config served a call."""
    seen: list[str] = []

    async def fake_acompletion(**kwargs):
        seen.append(kwargs["api_key"])
        return _FakeResponse('{"ok": true}', usage=_FakeUsage(3, 4))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.01)
    return seen


def test_byok_off_uses_the_portal_key_for_every_project(client, monkeypatch):
    seen = _record_keys(monkeypatch)

    async def run():
        await _config(name="Portal", api_key="sk-portal")
        await _config(name="Project", api_key="sk-project", project_id=PROJECT_A)
        await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=PROJECT_A)

    asyncio.run(run())
    assert seen == ["sk-portal"]


def test_byok_on_uses_the_projects_own_key(client, monkeypatch):
    seen = _record_keys(monkeypatch)

    async def run():
        await _config(name="Portal", api_key="sk-portal")
        await _config(name="Project", api_key="sk-project", project_id=PROJECT_A)
        await ai_provider_config_service.set_byok_enabled(True)
        await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=PROJECT_A)

    asyncio.run(run())
    assert seen == ["sk-project"]


def test_byok_on_without_a_project_key_refuses_rather_than_billing_the_portal(client, monkeypatch):
    seen = _record_keys(monkeypatch)

    async def run():
        await _config(name="Portal", api_key="sk-portal")
        await ai_provider_config_service.set_byok_enabled(True)
        with pytest.raises(llm_client.LLMNotConfiguredError) as exc:
            await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=PROJECT_A)
        # The message has to name the page that fixes it -- "no provider configured" alone sends
        # the project owner to the admin, who can't help them.
        assert "Project → Settings → AI Provider" in str(exc.value)

    asyncio.run(run())
    assert seen == []


def test_byok_on_does_not_fail_over_from_a_project_key_to_the_portal_key(client, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    seen: list[str] = []

    async def fake_acompletion(**kwargs):
        seen.append(kwargs["api_key"])
        raise litellm.RateLimitError(message="slow down", llm_provider="openai", model="gpt-4o")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        await _config(name="Portal", api_key="sk-portal")
        await _config(name="Project", api_key="sk-project", project_id=PROJECT_A)
        await ai_provider_config_service.set_byok_enabled(True)
        with pytest.raises(llm_client.LLMTransientError):
            await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=PROJECT_A)

    asyncio.run(run())
    assert set(seen) == {"sk-project"}


def test_byok_on_isolates_two_projects_from_each_other(client, monkeypatch):
    seen = _record_keys(monkeypatch)
    project_b = "bbbbbbbbbbbbbbbbbbbbbbbb"

    async def run():
        await _config(name="A", api_key="sk-a", project_id=PROJECT_A)
        await _config(name="B", api_key="sk-b", project_id=project_b)
        await ai_provider_config_service.set_byok_enabled(True)
        await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=PROJECT_A)
        await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=project_b)

    asyncio.run(run())
    assert seen == ["sk-a", "sk-b"]


def test_byok_on_refuses_a_call_with_no_project_attribution(client, monkeypatch):
    seen = _record_keys(monkeypatch)

    async def run():
        await _config(name="Portal", api_key="sk-portal")
        await ai_provider_config_service.set_byok_enabled(True)
        with pytest.raises(llm_client.LLMNotConfiguredError):
            await llm_client.get_completion([{"role": "user", "content": "hi"}])

    asyncio.run(run())
    assert seen == []


def test_tool_capability_gate_is_answered_per_project(client):
    async def run():
        # LM Studio is not in remediation_tool_capable_providers; anthropic is.
        await ai_provider_config_service.create_config(
            name="Local",
            provider="lmstudio",
            model_name="local-model",
            base_url="http://localhost:1234",
            temperature=0.0,
            api_key=None,
            created_by=None,
            project_id=PROJECT_A,
        )
        await ai_provider_config_service.create_config(
            name="Cloud",
            provider="anthropic",
            model_name="claude-sonnet-4-5",
            base_url=None,
            temperature=0.0,
            api_key="sk-ant",
            created_by=None,
            project_id="bbbbbbbbbbbbbbbbbbbbbbbb",
        )
        await ai_provider_config_service.set_byok_enabled(True)

        assert await llm_client.active_provider_supports_tools(PROJECT_A) is False
        assert await llm_client.active_provider_supports_tools("bbbbbbbbbbbbbbbbbbbbbbbb") is True

    asyncio.run(run())


def test_every_call_is_logged_including_failures(client, monkeypatch):
    """Failures used to leave no per-project trace at all, which is what made a broken project key
    undiagnosable from the dashboard."""
    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    monkeypatch.setattr(litellm, "completion_cost", lambda **_: 0.02)
    outcomes = iter([True, False])

    async def fake_acompletion(**kwargs):
        if next(outcomes):
            return _FakeResponse('{"ok": true}', usage=_FakeUsage(11, 7))
        raise litellm.AuthenticationError(message="bad key", llm_provider="openai", model="gpt-4o")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        await _config(name="Portal", api_key="sk-portal")
        await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=PROJECT_A,
                                        feature="analysis")
        with pytest.raises(llm_client.LLMPermanentError):
            await llm_client.get_completion([{"role": "user", "content": "hi"}], project_id=PROJECT_A,
                                            feature="autofix")

        events = await AIUsageEvent.find(AIUsageEvent.project_id == PROJECT_A).to_list()
        by_feature = {e.feature: e for e in events}
        assert set(by_feature) == {"analysis", "autofix"}

        ok = by_feature["analysis"]
        assert (ok.status, ok.prompt_tokens, ok.completion_tokens) == ("success", 11, 7)
        assert ok.cost_usd == 0.02 and ok.provider == "openai" and ok.model_name == "gpt-4o"
        assert ok.scope == "project" and ok.error_type is None

        bad = by_feature["autofix"]
        assert (bad.status, bad.error_type) == ("failed", "LLMPermanentError")
        # An error row still identifies the provider it failed against -- otherwise a project with
        # two configured keys can't tell which one is broken.
        assert bad.provider == "openai"

    asyncio.run(run())

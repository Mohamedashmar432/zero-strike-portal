import asyncio

import litellm
import pytest

import app.services.llm_client as llm_client
from app.core.config import settings
from app.models.ai_provider_config import AIProviderConfig
from app.services import ai_provider_config_service


async def _create_active_config(name="Primary", model_name="gpt-4o", api_key="sk-test") -> AIProviderConfig:
    return await ai_provider_config_service.create_config(
        name=name,
        provider="openai",
        model_name=model_name,
        base_url=None,
        temperature=0.0,
        api_key=api_key,
        created_by=None,
    )


async def _no_delay(*_args, **_kwargs):
    return None


class _FakeUsage:
    def __init__(self, prompt_tokens=0, completion_tokens=0):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content, usage=None):
        self.choices = [_FakeChoice(content)]
        self.usage = usage if usage is not None else _FakeUsage()


def test_not_configured_short_circuits_without_network_call(client, monkeypatch):
    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        return _FakeResponse("{}")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        with pytest.raises(llm_client.LLMNotConfiguredError):
            await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert calls["n"] == 0

    asyncio.run(run())


def test_retry_then_succeed(client, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise litellm.APIConnectionError(message="conn reset", llm_provider="openai", model="gpt-4o")
        return _FakeResponse('{"ok": true}')

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        await _create_active_config()
        result = await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert result == {"ok": True}
        assert calls["n"] == 3

    asyncio.run(run())


def test_permanent_error_does_not_retry_and_records_failure(client, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        raise litellm.AuthenticationError(message="bad key", llm_provider="openai", model="gpt-4o")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        config = await _create_active_config()
        with pytest.raises(llm_client.LLMPermanentError):
            await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert calls["n"] == 1  # never retried

        reloaded = await AIProviderConfig.get(config.id)
        assert reloaded.total_requests == 1
        assert reloaded.total_failed_requests == 1
        assert reloaded.total_prompt_tokens == 0
        assert reloaded.total_completion_tokens == 0
        assert reloaded.total_cost_usd == 0.0
        assert reloaded.last_used_at is not None

    asyncio.run(run())


def test_exhausted_retries_raises_transient_error_and_records_failure(client, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        raise litellm.RateLimitError(message="rate limited", llm_provider="openai", model="gpt-4o")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        config = await _create_active_config()
        with pytest.raises(llm_client.LLMTransientError):
            await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert calls["n"] == 3  # 3 attempts total, then gave up

        reloaded = await AIProviderConfig.get(config.id)
        assert reloaded.total_requests == 1
        assert reloaded.total_failed_requests == 1
        assert reloaded.total_prompt_tokens == 0
        assert reloaded.total_completion_tokens == 0
        assert reloaded.total_cost_usd == 0.0

    asyncio.run(run())


def test_malformed_response_raises_and_is_not_retried_but_counts_as_success(client, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        return _FakeResponse("this is not json", usage=_FakeUsage(prompt_tokens=12, completion_tokens=3))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        config = await _create_active_config()
        with pytest.raises(llm_client.LLMMalformedResponseError):
            await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert calls["n"] == 1  # the call itself succeeded -- no retry for a parse failure

        # The provider call itself succeeded and was billed -- only our parsing failed, so
        # usage is recorded as a success before the json.loads is attempted.
        reloaded = await AIProviderConfig.get(config.id)
        assert reloaded.total_requests == 1
        assert reloaded.total_failed_requests == 0
        assert reloaded.total_prompt_tokens == 12
        assert reloaded.total_completion_tokens == 3

    asyncio.run(run())


def test_get_completion_resolves_active_config_when_two_exist(client, monkeypatch):
    captured_kwargs = {}

    async def fake_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return _FakeResponse('{"ok": true}', usage=_FakeUsage(prompt_tokens=5, completion_tokens=2))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        await _create_active_config(name="Inactive-ish", model_name="gpt-4o", api_key="sk-first")
        active = await ai_provider_config_service.create_config(
            name="Second",
            provider="anthropic",
            model_name="claude-haiku-4-5",
            base_url=None,
            temperature=0.0,
            api_key="sk-second",
            created_by=None,
        )
        await ai_provider_config_service.set_active(str(active.id))

        result = await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert result == {"ok": True}
        assert captured_kwargs["model"] == "claude-haiku-4-5"
        assert captured_kwargs["api_key"] == "sk-second"
        assert captured_kwargs["timeout"] == settings.ai_llm_request_timeout_seconds

        reloaded = await AIProviderConfig.get(active.id)
        assert reloaded.total_requests == 1
        assert reloaded.total_prompt_tokens == 5
        assert reloaded.total_completion_tokens == 2

    asyncio.run(run())


def test_successful_call_records_cost_via_completion_cost(client, monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse('{"ok": true}', usage=_FakeUsage(prompt_tokens=10, completion_tokens=4))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(litellm, "completion_cost", lambda **kwargs: 0.0042)

    async def run():
        config = await _create_active_config()
        await llm_client.get_completion([{"role": "user", "content": "hi"}])

        reloaded = await AIProviderConfig.get(config.id)
        assert reloaded.total_requests == 1
        assert reloaded.total_prompt_tokens == 10
        assert reloaded.total_completion_tokens == 4
        assert reloaded.total_cost_usd == pytest.approx(0.0042)
        assert reloaded.last_used_at is not None

    asyncio.run(run())


def test_completion_cost_failure_does_not_propagate_and_records_zero_cost(client, monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse('{"ok": true}', usage=_FakeUsage(prompt_tokens=10, completion_tokens=4))

    def _raise_cost(**kwargs):
        raise ValueError("no pricing entry for this model")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    monkeypatch.setattr(litellm, "completion_cost", _raise_cost)

    async def run():
        config = await _create_active_config()
        result = await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert result == {"ok": True}  # the cost-calc failure never surfaces as an error

        reloaded = await AIProviderConfig.get(config.id)
        assert reloaded.total_cost_usd == 0.0
        assert reloaded.total_prompt_tokens == 10

    asyncio.run(run())


def test_connection_succeeds_with_zero_providers_in_db(client, monkeypatch):
    async def fake_acompletion(**kwargs):
        assert kwargs["model"] == "gpt-4o"
        assert kwargs["api_key"] == "sk-draft"
        return _FakeResponse("pong")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        assert await AIProviderConfig.find().count() == 0
        result = await llm_client.test_connection(
            provider="openai", model_name="gpt-4o", api_key="sk-draft", base_url=None
        )
        assert result is None
        assert await AIProviderConfig.find().count() == 0  # still bypassed persistence entirely

    asyncio.run(run())


def test_connection_fails_with_permanent_error(client, monkeypatch):
    async def fake_acompletion(**kwargs):
        raise litellm.AuthenticationError(message="bad key", llm_provider="openai", model="gpt-4o")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        with pytest.raises(llm_client.LLMPermanentError):
            await llm_client.test_connection(
                provider="openai", model_name="gpt-4o", api_key="sk-bad", base_url=None
            )

    asyncio.run(run())


def test_connection_maps_unmapped_api_error_to_permanent(client, monkeypatch):
    """Regression: litellm raises the bare base litellm.APIError for statuses it doesn't map to a
    specific subclass (e.g. CommandCode's 403 "Go plan doesn't include API access"). That used to
    escape test_connection uncaught -> the router's `except LLMError` missed it -> opaque 500 with
    no reason. It must now surface as LLMPermanentError so the real message reaches the admin."""

    async def fake_acompletion(**kwargs):
        raise litellm.APIError(
            status_code=403,
            message="Your Go plan doesn't include API access.",
            llm_provider="openai",
            model="deepseek/deepseek-v4-flash",
        )

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        with pytest.raises(llm_client.LLMPermanentError, match="Go plan"):
            await llm_client.test_connection(
                provider="commandcode",
                model_name="deepseek/deepseek-v4-flash",
                api_key="user_x",
                base_url="https://api.commandcode.ai/provider/v1",
            )

    asyncio.run(run())


def test_connection_fails_with_transient_error_after_retries(client, monkeypatch):
    monkeypatch.setattr(asyncio, "sleep", _no_delay)
    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        raise litellm.RateLimitError(message="rate limited", llm_provider="openai", model="gpt-4o")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        with pytest.raises(llm_client.LLMTransientError):
            await llm_client.test_connection(
                provider="openai", model_name="gpt-4o", api_key="sk-x", base_url=None
            )
        assert calls["n"] == 3

    asyncio.run(run())


@pytest.mark.parametrize(
    "provider,model_in,base_in,model_out,base_out",
    [
        # anthropic/openai: litellm resolves these natively from the bare name -- untouched.
        ("anthropic", "claude-haiku-4-5", None, "claude-haiku-4-5", None),
        ("openai", "gpt-4o", None, "gpt-4o", None),
        # nvidia_nim/openrouter: litellm's own provider-prefix convention.
        ("nvidia_nim", "meta/llama-3.1-70b-instruct", None, "nvidia_nim/meta/llama-3.1-70b-instruct", None),
        ("nvidia_nim", "kimi-k2.6", "https://integrate.api.nvidia.com/v1", "nvidia_nim/kimi-k2.6",
         "https://integrate.api.nvidia.com/v1"),
        ("openrouter", "openai/gpt-4o", None, "openrouter/openai/gpt-4o", None),
        # groq: litellm's native provider prefix, key required, no base_url needed.
        ("groq", "llama-3.3-70b-versatile", None, "groq/llama-3.3-70b-versatile", None),
        # already-prefixed by the admin themselves -- must not be double-prefixed.
        ("nvidia_nim", "nvidia_nim/meta/llama-3.1-70b-instruct", None,
         "nvidia_nim/meta/llama-3.1-70b-instruct", None),
        # lmstudio/custom: OpenAI-compatible over a required, admin-supplied base_url.
        ("lmstudio", "loaded-model", "http://localhost:1234/v1", "openai/loaded-model",
         "http://localhost:1234/v1"),
        ("custom", "my-model", "https://my-host.example/v1", "openai/my-model", "https://my-host.example/v1"),
        # kimi: OpenAI-compatible with a built-in default base_url when the admin left it blank.
        ("kimi", "moonshot-v1-32k", None, "openai/moonshot-v1-32k", "https://api.moonshot.ai/v1"),
        ("kimi", "moonshot-v1-32k", "https://custom-mirror.example/v1", "openai/moonshot-v1-32k",
         "https://custom-mirror.example/v1"),
        # commandcode: OpenAI-compatible with a built-in default base_url, same as kimi.
        ("commandcode", "deepseek/deepseek-v4-flash", None, "openai/deepseek/deepseek-v4-flash",
         "https://api.commandcode.ai/provider/v1"),
        # a base_url missing /v1 (the common LM Studio/Ollama/vLLM gotcha) gets it appended.
        ("lmstudio", "loaded-model", "http://127.0.0.1:1234", "openai/loaded-model",
         "http://127.0.0.1:1234/v1"),
        ("lmstudio", "loaded-model", "http://127.0.0.1:1234/", "openai/loaded-model",
         "http://127.0.0.1:1234/v1"),
    ],
)
def test_resolve_model_and_base(provider, model_in, base_in, model_out, base_out):
    model, base = llm_client._resolve_model_and_base(provider, model_in, base_in)
    assert model == model_out
    assert base == base_out


@pytest.mark.parametrize(
    "provider,api_key,expected",
    [
        # self-hosted, no key needed -- a missing key gets a placeholder so the call still
        # reaches the server instead of erroring inside the openai SDK's client construction.
        ("lmstudio", None, "not-needed"),
        ("custom", "", "not-needed"),
        # hosted providers always need a real key -- a missing one stays missing, so the
        # caller gets a real upstream auth error instead of a fake "success".
        ("kimi", None, None),
        ("commandcode", None, None),
        ("anthropic", None, None),
        ("nvidia_nim", None, None),
        # an explicitly supplied key is always passed through untouched.
        ("lmstudio", "sk-real", "sk-real"),
        ("openai", "sk-real", "sk-real"),
    ],
)
def test_resolve_api_key(provider, api_key, expected):
    assert llm_client._resolve_api_key(provider, api_key) == expected


def test_connection_uses_placeholder_key_for_self_hosted_with_no_key(client, monkeypatch):
    """Regression test: LM Studio needs no API key, but leaving it blank used to raise
    litellm.AuthenticationError from the openai SDK before ever reaching the local server."""

    async def fake_acompletion(**kwargs):
        assert kwargs["api_key"] == "not-needed"
        assert kwargs["model"] == "openai/loaded-model"
        return _FakeResponse("pong")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        await llm_client.test_connection(
            provider="lmstudio",
            model_name="loaded-model",
            api_key=None,
            base_url="http://localhost:1234/v1",
        )

    asyncio.run(run())


def test_connection_prefixes_model_for_nvidia_nim(client, monkeypatch):
    """Regression test for the exact bug report: provider=nvidia_nim + a bare model name
    used to reach litellm unprefixed, raising "LLM Provider NOT provided"."""

    async def fake_acompletion(**kwargs):
        assert kwargs["model"] == "nvidia_nim/kimi-k2.6"
        assert kwargs["api_base"] == "https://integrate.api.nvidia.com/v1"
        return _FakeResponse("pong")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        await llm_client.test_connection(
            provider="nvidia_nim",
            model_name="kimi-k2.6",
            api_key="test-key",
            base_url="https://integrate.api.nvidia.com/v1",
        )

    asyncio.run(run())


@pytest.mark.parametrize(
    "content,expected",
    [
        ('{"ok": true}', {"ok": True}),
        ('```json\n{"ok": true}\n```', {"ok": True}),
        ('```\n{"ok": true}\n```', {"ok": True}),
        ('Sure! Here is the JSON:\n{"ok": true}\nHope that helps.', {"ok": True}),
        ('{"findings": [{"fingerprint": "a"}]}', {"findings": [{"fingerprint": "a"}]}),
    ],
)
def test_extract_json_tolerates_fences_and_prose(content, expected):
    assert llm_client._extract_json(content) == expected


@pytest.mark.parametrize("content", ["not json at all", "", "```json\nnope\n```"])
def test_extract_json_raises_when_unparseable(content):
    with pytest.raises(llm_client.LLMMalformedResponseError):
        llm_client._extract_json(content)


def test_get_completion_sends_response_format_only_for_json_object_providers(client, monkeypatch):
    seen = {}

    async def fake_acompletion(**kwargs):
        seen["response_format"] = kwargs.get("response_format")
        return _FakeResponse('{"ok": true}', usage=_FakeUsage(1, 1))

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        # openai supports json_object -> the kwarg is sent.
        await _create_active_config(name="oai", model_name="gpt-4o", api_key="sk-x")
        await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert seen["response_format"] == {"type": "json_object"}

        # lmstudio (OpenAI-compatible local) rejects json_object -> the kwarg is omitted.
        lm = await ai_provider_config_service.create_config(
            name="lm", provider="lmstudio", model_name="loaded-model",
            base_url="http://localhost:1234/v1", temperature=0.0, api_key=None, created_by=None,
        )
        await ai_provider_config_service.set_active(str(lm.id))
        seen.clear()
        await llm_client.get_completion([{"role": "user", "content": "hi"}])
        assert "response_format" not in seen or seen.get("response_format") is None

    asyncio.run(run())


def test_connection_never_records_usage(client, monkeypatch):
    async def fake_acompletion(**kwargs):
        return _FakeResponse("pong")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    async def run():
        config = await _create_active_config()
        await llm_client.test_connection(
            provider="openai", model_name=config.model_name, api_key="sk-test", base_url=None
        )
        reloaded = await AIProviderConfig.get(config.id)
        assert reloaded.total_requests == 0  # test pings never count toward usage totals

    asyncio.run(run())

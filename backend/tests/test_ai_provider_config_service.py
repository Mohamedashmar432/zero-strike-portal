import asyncio

import pytest
from fastapi import HTTPException

from app.core import security
from app.models.ai_provider_config import AIProviderConfig
from app.services import ai_provider_config_service


def test_create_config_auto_activates_first_bootstrap(client):
    async def run():
        assert await AIProviderConfig.find().count() == 0
        config = await ai_provider_config_service.create_config(
            name="Primary",
            provider="openai",
            model_name="gpt-4o",
            base_url=None,
            temperature=0.0,
            api_key="sk-a",
            created_by="user-1",
        )
        assert config.is_active is True

        second = await ai_provider_config_service.create_config(
            name="Secondary",
            provider="anthropic",
            model_name="claude-haiku-4-5",
            base_url=None,
            temperature=0.0,
            api_key="sk-b",
            created_by="user-1",
        )
        assert second.is_active is False

    asyncio.run(run())


def test_create_config_auto_activates_when_collection_emptied_then_readded(client):
    async def run():
        first = await ai_provider_config_service.create_config(
            name="Primary",
            provider="openai",
            model_name="gpt-4o",
            base_url=None,
            temperature=0.0,
            api_key="sk-a",
            created_by=None,
        )
        assert first.is_active is True
        await ai_provider_config_service.delete_config(str(first.id))
        assert await AIProviderConfig.find().count() == 0

        replacement = await ai_provider_config_service.create_config(
            name="Replacement",
            provider="anthropic",
            model_name="claude-haiku-4-5",
            base_url=None,
            temperature=0.0,
            api_key="sk-c",
            created_by=None,
        )
        assert replacement.is_active is True

    asyncio.run(run())


def test_multiple_providers_coexist(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        b = await ai_provider_config_service.create_config(
            name="B", provider="anthropic", model_name="claude-haiku-4-5", base_url=None,
            temperature=0.0, api_key="sk-b", created_by=None,
        )
        configs = await ai_provider_config_service.list_configs()
        ids = {str(c.id) for c in configs}
        assert ids == {str(a.id), str(b.id)}
        # sorted -created_at -> most recently created first
        assert str(configs[0].id) == str(b.id)

    asyncio.run(run())


def test_set_active_flips_exactly_one_and_none_clears(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        b = await ai_provider_config_service.create_config(
            name="B", provider="anthropic", model_name="claude-haiku-4-5", base_url=None,
            temperature=0.0, api_key="sk-b", created_by=None,
        )
        assert a.is_active is True
        assert b.is_active is False

        await ai_provider_config_service.set_active(str(b.id))
        reloaded_a = await AIProviderConfig.get(a.id)
        reloaded_b = await AIProviderConfig.get(b.id)
        assert reloaded_a.is_active is False
        assert reloaded_b.is_active is True

        await ai_provider_config_service.set_active(None)
        reloaded_a = await AIProviderConfig.get(a.id)
        reloaded_b = await AIProviderConfig.get(b.id)
        assert reloaded_a.is_active is False
        assert reloaded_b.is_active is False
        assert await ai_provider_config_service.get_active_config() is None

    asyncio.run(run())


def test_update_config_never_mutates_is_active(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        assert a.is_active is True
        updated = await ai_provider_config_service.update_config(
            str(a.id),
            name="A renamed",
            provider="openai",
            model_name="gpt-4o-mini",
            base_url=None,
            temperature=0.5,
            api_key=None,
            clear_api_key=False,
            updated_by="user-2",
        )
        assert updated.is_active is True
        assert updated.name == "A renamed"
        assert updated.model_name == "gpt-4o-mini"
        assert updated.temperature == 0.5
        assert updated.updated_by == "user-2"

    asyncio.run(run())


def test_update_config_raises_400_if_it_would_break_active_provider(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        assert a.is_active is True
        with pytest.raises(HTTPException) as exc_info:
            await ai_provider_config_service.update_config(
                str(a.id),
                name="A",
                provider="openai",
                model_name=None,
                base_url=None,
                temperature=None,
                api_key=None,
                clear_api_key=False,
                updated_by=None,
            )
        assert exc_info.value.status_code == 400
        reloaded = await AIProviderConfig.get(a.id)
        assert reloaded.model_name == "gpt-4o"  # unchanged -- nothing persisted

    asyncio.run(run())


def test_update_config_allows_incomplete_state_when_not_active(client):
    async def run():
        await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        b = await ai_provider_config_service.create_config(
            name="B", provider="anthropic", model_name="claude-haiku-4-5", base_url=None,
            temperature=0.0, api_key="sk-b", created_by=None,
        )
        assert b.is_active is False
        updated = await ai_provider_config_service.update_config(
            str(b.id),
            name="B",
            provider="anthropic",
            model_name=None,
            base_url=None,
            temperature=None,
            api_key=None,
            clear_api_key=False,
            updated_by=None,
        )
        assert updated.model_name is None
        assert updated.is_active is False

    asyncio.run(run())


def test_update_config_omitted_api_key_keeps_existing(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-original", created_by=None,
        )
        updated = await ai_provider_config_service.update_config(
            str(a.id),
            name="A",
            provider="openai",
            model_name="gpt-4o-mini",
            base_url=None,
            temperature=None,
            api_key=None,
            clear_api_key=False,
            updated_by=None,
        )
        assert updated.model_name == "gpt-4o-mini"
        assert security.decrypt_secret(updated.api_key_encrypted) == "sk-original"

    asyncio.run(run())


def test_update_config_clear_api_key_wipes_it(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-original", created_by=None,
        )
        # Add a second provider so clearing A's key doesn't make it "the active-with-broken-config"
        # 400 path collide with what this test is checking.
        await ai_provider_config_service.set_active(None)
        updated = await ai_provider_config_service.update_config(
            str(a.id),
            name="A",
            provider="openai",
            model_name="gpt-4o",
            base_url=None,
            temperature=None,
            api_key=None,
            clear_api_key=True,
            updated_by=None,
        )
        assert updated.api_key_encrypted is None

    asyncio.run(run())


def test_delete_config_on_active_leaves_none_active(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        assert a.is_active is True
        await ai_provider_config_service.delete_config(str(a.id))
        assert await ai_provider_config_service.get_active_config() is None

    asyncio.run(run())


def test_delete_config_404_for_missing(client):
    async def run():
        with pytest.raises(HTTPException) as exc_info:
            await ai_provider_config_service.get_config_or_404("000000000000000000000000")
        assert exc_info.value.status_code == 404

    asyncio.run(run())


def test_is_ready_reflects_active_config(client):
    async def run():
        assert await ai_provider_config_service.is_ready() is False
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        assert a.is_active is True
        assert await ai_provider_config_service.is_ready() is True

        await ai_provider_config_service.set_active(None)
        assert await ai_provider_config_service.is_ready() is False

    asyncio.run(run())


@pytest.mark.parametrize(
    "provider,model_name,has_key,expected",
    [
        ("openai", "gpt-4o", True, True),
        (None, "gpt-4o", True, False),
        ("openai", None, True, False),
        ("openai", "gpt-4o", False, False),
    ],
)
def test_is_ready_truth_table_for_explicit_config(client, provider, model_name, has_key, expected):
    async def run():
        config = AIProviderConfig(
            provider=provider or "anthropic",
            model_name=model_name,
            api_key_encrypted=security.encrypt_secret("k") if has_key else None,
        )
        if provider is None:
            config.provider = None  # simulate an incomplete config not expressible via the Literal type
        assert await ai_provider_config_service.is_ready(config) == expected

    asyncio.run(run())


@pytest.mark.parametrize("provider", ["lmstudio", "custom"])
def test_is_ready_true_without_key_for_self_hosted_providers(client, provider):
    async def run():
        config = AIProviderConfig(provider=provider, model_name="loaded-model", api_key_encrypted=None)
        assert await ai_provider_config_service.is_ready(config) is True

    asyncio.run(run())


def test_record_usage_is_atomic_and_attributed_to_correct_doc(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        b = await ai_provider_config_service.create_config(
            name="B", provider="anthropic", model_name="claude-haiku-4-5", base_url=None,
            temperature=0.0, api_key="sk-b", created_by=None,
        )

        await ai_provider_config_service.record_usage(
            str(a.id), success=True, prompt_tokens=10, completion_tokens=5, cost_usd=0.01
        )
        await ai_provider_config_service.record_usage(
            str(a.id), success=True, prompt_tokens=20, completion_tokens=8, cost_usd=0.02
        )
        await ai_provider_config_service.record_usage(str(b.id), success=False)

        reloaded_a = await AIProviderConfig.get(a.id)
        reloaded_b = await AIProviderConfig.get(b.id)

        assert reloaded_a.total_requests == 2
        assert reloaded_a.total_failed_requests == 0
        assert reloaded_a.total_prompt_tokens == 30
        assert reloaded_a.total_completion_tokens == 13
        assert reloaded_a.total_cost_usd == pytest.approx(0.03)
        assert reloaded_a.last_used_at is not None

        assert reloaded_b.total_requests == 1
        assert reloaded_b.total_failed_requests == 1
        assert reloaded_b.total_prompt_tokens == 0
        assert reloaded_b.total_completion_tokens == 0
        assert reloaded_b.total_cost_usd == 0.0
        assert reloaded_b.last_used_at is not None

    asyncio.run(run())


def test_record_usage_concurrent_calls_do_not_lose_increments(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key="sk-a", created_by=None,
        )
        await asyncio.gather(
            *(
                ai_provider_config_service.record_usage(
                    str(a.id), success=True, prompt_tokens=1, completion_tokens=1, cost_usd=0.001
                )
                for _ in range(20)
            )
        )
        reloaded = await AIProviderConfig.get(a.id)
        assert reloaded.total_requests == 20
        assert reloaded.total_prompt_tokens == 20
        assert reloaded.total_completion_tokens == 20

    asyncio.run(run())


def test_update_config_encrypts_api_key_never_stores_raw(client):
    async def run():
        a = await ai_provider_config_service.create_config(
            name="A", provider="openai", model_name="gpt-4o", base_url=None,
            temperature=0.0, api_key=None, created_by=None,
        )
        updated = await ai_provider_config_service.update_config(
            str(a.id),
            name="A",
            provider="openai",
            model_name="gpt-4o",
            base_url=None,
            temperature=0.2,
            api_key="sk-super-secret",
            clear_api_key=False,
            updated_by="user-1",
        )
        assert updated.api_key_encrypted is not None
        assert updated.api_key_encrypted != "sk-super-secret"
        assert security.decrypt_secret(updated.api_key_encrypted) == "sk-super-secret"

    asyncio.run(run())

"""Manages the multi-provider AIProviderConfig collection: CRUD, which one (if any) is
"active" (the one llm_client actually uses), and per-provider running usage/cost totals.

The provider API key is encrypted at rest via app.core.security's existing Fernet
helpers (built on settings.oauth_encryption_key) -- reused as-is, no new crypto code.
"""

from datetime import datetime, timezone

from beanie import PydanticObjectId
from beanie.operators import Inc, Set
from fastapi import HTTPException, status

from app.core import security
from app.models.ai_provider_config import NO_KEY_REQUIRED_PROVIDERS, AIProvider, AIProviderConfig


async def list_configs() -> list[AIProviderConfig]:
    # -_id is a stable tiebreaker: two configs created in the same millisecond (coarse clock on
    # Windows) would otherwise order nondeterministically. ObjectIds are monotonic with insertion.
    return await AIProviderConfig.find().sort("-created_at", "-_id").to_list()


async def get_config_or_404(config_id: str) -> AIProviderConfig:
    config = await AIProviderConfig.get(config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "AI provider config not found")
    return config


async def get_active_config() -> AIProviderConfig | None:
    return await AIProviderConfig.find_one(AIProviderConfig.is_active == True)  # noqa: E712


def decrypt_api_key(config: AIProviderConfig) -> str | None:
    if not config.api_key_encrypted:
        return None
    return security.decrypt_secret(config.api_key_encrypted)


async def is_ready(config: AIProviderConfig | None = None) -> bool:
    """provider AND model_name AND (a resolvable key, or a provider that needs none) on the
    *active* config."""
    if config is None:
        config = await get_active_config()
    if config is None:
        return False
    if not config.provider or not config.model_name:
        return False
    if config.provider in NO_KEY_REQUIRED_PROVIDERS:
        return True
    return decrypt_api_key(config) is not None


async def create_config(
    *,
    name: str,
    provider: AIProvider,
    model_name: str | None,
    base_url: str | None,
    temperature: float,
    api_key: str | None,
    created_by: str | None,
) -> AIProviderConfig:
    """Auto-activates iff the collection was empty before this insert -- the first provider
    ever added becomes active automatically; every subsequent one starts inactive."""
    was_empty = await AIProviderConfig.find().count() == 0
    now = datetime.now(timezone.utc)
    config = AIProviderConfig(
        name=name,
        provider=provider,
        model_name=model_name,
        base_url=base_url,
        temperature=temperature,
        api_key_encrypted=security.encrypt_secret(api_key) if api_key else None,
        is_active=was_empty,
        created_at=now,
        updated_at=now,
        updated_by=created_by,
    )
    await config.insert()
    return config


async def update_config(
    config_id: str,
    *,
    name: str,
    provider: AIProvider,
    model_name: str | None,
    base_url: str | None,
    temperature: float | None,
    api_key: str | None,
    clear_api_key: bool,
    updated_by: str | None,
) -> AIProviderConfig:
    """Applies the update payload's omitted-vs-clear api_key semantics:
    - api_key omitted (None) and clear_api_key falsy -> existing encrypted key untouched.
    - clear_api_key=True -> api_key_encrypted wiped, regardless of an api_key also being sent.
    - api_key provided (non-empty) -> re-encrypted and stored, replacing whatever was there.

    Never touches is_active. Raises 400 if this config is currently active and the
    prospective (post-update) state would leave it not ready -- an admin editing the live
    active provider must not be able to silently break it.
    """
    config = await get_config_or_404(config_id)
    config.name = name
    config.provider = provider
    config.model_name = model_name
    config.base_url = base_url
    if temperature is not None:
        config.temperature = temperature

    if clear_api_key:
        config.api_key_encrypted = None
    elif api_key:
        config.api_key_encrypted = security.encrypt_secret(api_key)

    if config.is_active and not await is_ready(config):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This provider is currently active and requires a model name and API key.",
        )

    config.updated_at = datetime.now(timezone.utc)
    config.updated_by = updated_by
    await config.save()
    return config


async def delete_config(config_id: str) -> None:
    config = await get_config_or_404(config_id)
    await config.delete()


async def set_active(config_id: str | None) -> AIProviderConfig | None:
    """Deactivates whichever provider is currently active, then (if config_id is given)
    activates that one. config_id=None deactivates everything -- turns AI analysis off.

    Two sequential writes, not a transaction -- this is a rare single-admin action with
    no meaningful concurrency risk.
    """
    await AIProviderConfig.find(AIProviderConfig.is_active == True).update(  # noqa: E712
        Set({AIProviderConfig.is_active: False})
    )
    if config_id is None:
        return None
    config = await get_config_or_404(config_id)
    config.is_active = True
    await config.save()
    return config


async def record_usage(
    config_id: str,
    *,
    success: bool,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Atomic $inc so concurrent llm_client calls (analyze_findings_batch runs one call per
    rule_id group, gathered concurrently under a semaphore) against the same active
    provider never lose increments to a read-modify-write race."""
    now = datetime.now(timezone.utc)
    if success:
        inc = Inc(
            {
                AIProviderConfig.total_requests: 1,
                AIProviderConfig.total_prompt_tokens: prompt_tokens,
                AIProviderConfig.total_completion_tokens: completion_tokens,
                AIProviderConfig.total_cost_usd: cost_usd,
            }
        )
    else:
        inc = Inc(
            {
                AIProviderConfig.total_requests: 1,
                AIProviderConfig.total_failed_requests: 1,
            }
        )
    await AIProviderConfig.find_one(AIProviderConfig.id == PydanticObjectId(config_id)).update(
        inc, Set({AIProviderConfig.last_used_at: now})
    )

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import require_admin
from app.core.timeutils import as_utc as _as_utc
from app.models.ai_provider_config import AIProviderConfig
from app.models.user import User
from app.schemas.ai_provider_config import (
    AIProviderConfigCreateRequest,
    AIProviderConfigResponse,
    AIProviderConfigUpdateRequest,
    AIProviderTestRequest,
    AIProviderTestResponse,
)
from app.services import ai_provider_config_service, audit_service, llm_client

router = APIRouter(prefix="/ai/providers", tags=["ai-provider-config"])


def _to_response(config: AIProviderConfig) -> AIProviderConfigResponse:
    return AIProviderConfigResponse(
        id=str(config.id),
        name=config.name,
        provider=config.provider,
        model_name=config.model_name,
        base_url=config.base_url,
        temperature=config.temperature,
        is_active=config.is_active,
        has_api_key=config.api_key_encrypted is not None,
        total_requests=config.total_requests,
        total_failed_requests=config.total_failed_requests,
        total_prompt_tokens=config.total_prompt_tokens,
        total_completion_tokens=config.total_completion_tokens,
        total_cost_usd=config.total_cost_usd,
        last_used_at=_as_utc(config.last_used_at),
        created_at=_as_utc(config.created_at),
        updated_at=_as_utc(config.updated_at),
        updated_by=config.updated_by,
    )


@router.get("", response_model=list[AIProviderConfigResponse])
async def list_ai_providers(user: User = Depends(require_admin)):
    configs = await ai_provider_config_service.list_configs()
    return [_to_response(c) for c in configs]


@router.post("", response_model=AIProviderConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_ai_provider(payload: AIProviderConfigCreateRequest, user: User = Depends(require_admin)):
    config = await ai_provider_config_service.create_config(
        name=payload.name,
        provider=payload.provider,
        model_name=payload.model_name,
        base_url=payload.base_url,
        temperature=payload.temperature,
        api_key=payload.api_key,
        created_by=str(user.id),
    )
    await audit_service.record(
        "AI Provider Added",
        actor_user_id=str(user.id),
        target_type="ai_provider_config",
        target_id=str(config.id),
        metadata={"provider": config.provider, "name": config.name, "is_active": config.is_active},
    )
    return _to_response(config)


@router.get("/{provider_id}", response_model=AIProviderConfigResponse)
async def get_ai_provider(provider_id: str, user: User = Depends(require_admin)):
    config = await ai_provider_config_service.get_config_or_404(provider_id)
    return _to_response(config)


@router.put("/{provider_id}", response_model=AIProviderConfigResponse)
async def update_ai_provider(
    provider_id: str, payload: AIProviderConfigUpdateRequest, user: User = Depends(require_admin)
):
    config = await ai_provider_config_service.update_config(
        provider_id,
        name=payload.name,
        provider=payload.provider,
        model_name=payload.model_name,
        base_url=payload.base_url,
        temperature=payload.temperature,
        api_key=payload.api_key,
        clear_api_key=payload.clear_api_key,
        updated_by=str(user.id),
    )
    await audit_service.record(
        "AI Provider Updated",
        actor_user_id=str(user.id),
        target_type="ai_provider_config",
        target_id=str(config.id),
        metadata={"provider": config.provider, "name": config.name},
    )
    return _to_response(config)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_provider(provider_id: str, user: User = Depends(require_admin)):
    config = await ai_provider_config_service.get_config_or_404(provider_id)
    await ai_provider_config_service.delete_config(provider_id)
    await audit_service.record(
        "AI Provider Removed",
        actor_user_id=str(user.id),
        target_type="ai_provider_config",
        target_id=str(config.id),
        metadata={"provider": config.provider, "name": config.name},
    )


@router.post("/{provider_id}/activate", response_model=list[AIProviderConfigResponse])
async def activate_ai_provider(provider_id: str, user: User = Depends(require_admin)):
    # provider_id is always given here, so set_active never returns None -- it either
    # activates that config or raises 404 (never silently no-ops).
    config = await ai_provider_config_service.set_active(provider_id)
    await audit_service.record(
        "AI Provider Activated",
        actor_user_id=str(user.id),
        target_type="ai_provider_config",
        target_id=str(config.id),
        metadata={"provider": config.provider},
    )
    configs = await ai_provider_config_service.list_configs()
    return [_to_response(c) for c in configs]


@router.post("/deactivate", response_model=list[AIProviderConfigResponse])
async def deactivate_ai_provider(user: User = Depends(require_admin)):
    await ai_provider_config_service.set_active(None)
    await audit_service.record(
        "AI Provider Deactivated",
        actor_user_id=str(user.id),
        target_type="ai_provider_config",
        target_id=None,
    )
    configs = await ai_provider_config_service.list_configs()
    return [_to_response(c) for c in configs]


@router.post("/{provider_id}/test", response_model=AIProviderTestResponse)
async def test_ai_provider(provider_id: str, user: User = Depends(require_admin)):
    config = await ai_provider_config_service.get_config_or_404(provider_id)
    api_key = ai_provider_config_service.decrypt_api_key(config)
    try:
        await llm_client.test_connection(
            provider=config.provider,
            model_name=config.model_name,
            api_key=api_key,
            base_url=config.base_url,
            temperature=config.temperature,
        )
    except llm_client.LLMError as exc:
        await audit_service.record(
            "AI Provider Test Connection Failed",
            actor_user_id=str(user.id),
            target_type="ai_provider_config",
            target_id=str(config.id),
            metadata={"provider": config.provider, "error": str(exc)},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    await audit_service.record(
        "AI Provider Test Connection Succeeded",
        actor_user_id=str(user.id),
        target_type="ai_provider_config",
        target_id=str(config.id),
        metadata={"provider": config.provider},
    )
    return AIProviderTestResponse(message="Connection successful")


@router.post("/test", response_model=AIProviderTestResponse)
async def test_ai_provider_draft(payload: AIProviderTestRequest, user: User = Depends(require_admin)):
    try:
        await llm_client.test_connection(
            provider=payload.provider,
            model_name=payload.model_name,
            api_key=payload.api_key,
            base_url=payload.base_url,
            temperature=payload.temperature,
        )
    except llm_client.LLMError as exc:
        await audit_service.record(
            "AI Provider Test Connection Failed",
            actor_user_id=str(user.id),
            target_type="ai_provider_config",
            target_id=None,
            metadata={"provider": payload.provider, "error": str(exc)},
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    await audit_service.record(
        "AI Provider Test Connection Succeeded",
        actor_user_id=str(user.id),
        target_type="ai_provider_config",
        target_id=None,
        metadata={"provider": payload.provider},
    )
    return AIProviderTestResponse(message="Connection successful")

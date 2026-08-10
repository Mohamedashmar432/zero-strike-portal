from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user, require_admin
from app.models.ai_provider_config import AIProviderConfig
from app.models.user import User
from app.schemas.ai_provider_config import (
    AIProviderConfigCreateRequest,
    AIProviderConfigResponse,
    AIProviderConfigUpdateRequest,
    AIProviderTestRequest,
    AIProviderTestResponse,
    AISettingsResponse,
    AISettingsUpdateRequest,
)
from app.services import ai_provider_config_service, audit_service, llm_client

router = APIRouter(prefix="/ai/providers", tags=["ai-provider-config"])
# Workspace-level AI policy rather than one provider's config, so it gets its own path. Second
# router in the same module follows ai_analysis.py / compliance.py.
settings_router = APIRouter(prefix="/ai", tags=["ai-provider-config"])


def _to_response(config: AIProviderConfig) -> AIProviderConfigResponse:
    return AIProviderConfigResponse.from_config(config)


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
        # The raw exception is kept in the audit record above; the admin gets an actionable verdict.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, llm_client.connection_error_message(exc)
        ) from exc

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
        # The raw exception is kept in the audit record above; the admin gets an actionable verdict.
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, llm_client.connection_error_message(exc)
        ) from exc

    await audit_service.record(
        "AI Provider Test Connection Succeeded",
        actor_user_id=str(user.id),
        target_type="ai_provider_config",
        target_id=None,
        metadata={"provider": payload.provider},
    )
    return AIProviderTestResponse(message="Connection successful")


@settings_router.get("/settings", response_model=AISettingsResponse)
async def get_ai_settings(user: User = Depends(get_current_user)):
    """Readable by any signed-in user, unlike the rest of this router: it is a workspace policy
    flag, not a credential, and a project owner has to know whether the BYOK card belongs on their
    settings page. Writing it stays admin-only."""
    return AISettingsResponse(project_byok_enabled=await ai_provider_config_service.byok_enabled())


@settings_router.put("/settings", response_model=AISettingsResponse)
async def update_ai_settings(payload: AISettingsUpdateRequest, user: User = Depends(require_admin)):
    """Flipping this changes which key every AI call in the portal runs on, so it is audited like
    any other provider change. Switching it *on* immediately disables AI for projects that haven't
    added a key yet -- by design (see WorkspaceSettings.project_byok_enabled); the UI says so."""
    enabled = await ai_provider_config_service.set_byok_enabled(payload.project_byok_enabled)
    await audit_service.record(
        "Project BYOK Enabled" if enabled else "Project BYOK Disabled",
        actor_user_id=str(user.id),
        target_type="workspace_settings",
        target_id=None,
    )
    return AISettingsResponse(project_byok_enabled=enabled)

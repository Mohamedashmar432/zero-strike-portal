from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import require_admin
from app.core.timeutils import as_utc
from app.models.mcp_token import McpToken
from app.models.user import User
from app.schemas.mcp_token import McpTokenCreateRequest, McpTokenCreateResponse, McpTokenResponse
from app.services import audit_service, mcp_token_service

router = APIRouter(prefix="/admin/mcp-tokens", tags=["admin"])


def _to_response(token: McpToken) -> McpTokenResponse:
    return McpTokenResponse(
        id=str(token.id),
        label=token.label,
        prefix=token.prefix,
        created_at=as_utc(token.created_at),
        expires_at=as_utc(token.expires_at),
        revoked_at=as_utc(token.revoked_at),
        last_used_at=as_utc(token.last_used_at),
        last_used_ip=token.last_used_ip,
        is_active=mcp_token_service.is_active(token),
    )


@router.get("", response_model=list[McpTokenResponse])
async def list_mcp_tokens(user: User = Depends(require_admin)):
    """The caller's own tokens only — one admin cannot see or revoke another's."""
    return [_to_response(t) for t in await mcp_token_service.list_for_user(user)]


@router.post("", response_model=McpTokenCreateResponse, status_code=status.HTTP_201_CREATED)
async def issue_mcp_token(payload: McpTokenCreateRequest, user: User = Depends(require_admin)):
    token, raw = await mcp_token_service.issue(user, payload.label, payload.expires_in_days)
    await audit_service.record(
        "MCP credential issued",
        actor_user_id=str(user.id),
        target_type="mcp_token",
        target_id=str(token.id),
        metadata={"label": token.label, "prefix": token.prefix, "expires_at": token.expires_at.isoformat()},
    )
    return McpTokenCreateResponse(**_to_response(token).model_dump(), raw_token=raw)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_mcp_token(token_id: str, user: User = Depends(require_admin)):
    already = await McpToken.get(token_id)
    was_revoked = bool(already and already.revoked_at)
    token = await mcp_token_service.revoke(user, token_id)
    if token is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP token not found")
    if not was_revoked:
        await audit_service.record(
            "MCP credential revoked",
            actor_user_id=str(user.id),
            target_type="mcp_token",
            target_id=str(token.id),
            metadata={"label": token.label, "prefix": token.prefix},
        )

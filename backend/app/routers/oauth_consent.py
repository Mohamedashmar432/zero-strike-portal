"""Consent + connected apps for the user MCP endpoint (docs/USER_MCP_OAUTH.md). JWT-authenticated
(the signed-in portal user), unlike the OAuth endpoints the MCP client itself calls."""

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.deps import get_current_user
from app.core.timeutils import as_utc
from app.models.mcp_oauth import OAuthAuthorizationRequest, OAuthClient, OAuthGrant
from app.models.user import User
from app.schemas.mcp_oauth import ConnectedAppResponse, ConsentDecisionResponse, ConsentRequestResponse
from app.services import audit_service, mcp_oauth_service
from app.services.mcp_oauth_service import provider

router = APIRouter(prefix="/oauth", tags=["oauth"])

_GONE = "This authorization request has expired or was already used"


async def _client_name(client_id: str) -> str:
    doc = await OAuthClient.find_one(OAuthClient.client_id == client_id)
    return mcp_oauth_service.display_name(doc.info) if doc else "Unknown application"


def _audit_meta(req: OAuthAuthorizationRequest, name: str) -> dict:
    return {
        "client_name": name,
        "client_id": req.client_id,
        "redirect_host": mcp_oauth_service.redirect_host(req.redirect_uri),
        "scope": " ".join(req.scopes),
    }


@router.get("/requests/{request_id}", response_model=ConsentRequestResponse)
async def get_consent_request(request_id: str, user: User = Depends(get_current_user)):
    req = await provider.pending_request(request_id)
    if not req:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _GONE)
    return ConsentRequestResponse(
        request_id=req.request_id,
        client_name=await _client_name(req.client_id),
        redirect_host=mcp_oauth_service.redirect_host(req.redirect_uri),
        scopes=req.scopes,
        account_email=user.email,
        expires_at=as_utc(req.expires_at),
    )


@router.post("/requests/{request_id}/approve", response_model=ConsentDecisionResponse)
async def approve_consent_request(request_id: str, user: User = Depends(get_current_user)):
    result = await provider.approve(request_id, user)
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _GONE)
    req, redirect_to = result
    await audit_service.record(
        "MCP app authorized",
        actor_user_id=str(user.id),
        target_type="mcp_app",
        target_id=req.client_id,
        metadata=_audit_meta(req, await _client_name(req.client_id)),
    )
    return ConsentDecisionResponse(redirect_to=redirect_to)


@router.post("/requests/{request_id}/deny", response_model=ConsentDecisionResponse)
async def deny_consent_request(request_id: str, user: User = Depends(get_current_user)):
    result = await provider.deny(request_id)
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _GONE)
    req, redirect_to = result
    await audit_service.record(
        "MCP app access denied",
        actor_user_id=str(user.id),
        target_type="mcp_app",
        target_id=req.client_id,
        metadata={**_audit_meta(req, await _client_name(req.client_id)), "reason": "user denied consent"},
    )
    return ConsentDecisionResponse(redirect_to=redirect_to)


def _grant_response(g: OAuthGrant) -> ConnectedAppResponse:
    return ConnectedAppResponse(
        id=str(g.id),
        client_name=g.client_name,
        redirect_host=g.redirect_host,
        scopes=g.scopes,
        created_at=as_utc(g.created_at),
        last_used_at=as_utc(g.last_used_at),
    )


@router.get("/connected-apps", response_model=list[ConnectedAppResponse])
async def list_connected_apps(user: User = Depends(get_current_user)):
    return [_grant_response(g) for g in await mcp_oauth_service.list_grants(user)]


@router.delete("/connected-apps/{grant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_connected_app(grant_id: str, user: User = Depends(get_current_user)):
    grant = await mcp_oauth_service.revoke_user_grant(user, grant_id)
    if not grant:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connected app not found")
    await audit_service.record(
        "MCP app revoked",
        actor_user_id=str(user.id),
        target_type="mcp_app",
        target_id=grant.client_id,
        metadata={"client_name": grant.client_name, "redirect_host": grant.redirect_host},
    )

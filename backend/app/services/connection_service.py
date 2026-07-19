"""Orchestrates GitHub/Azure DevOps OAuth connections: authorize-url building, the callback exchange,
and resolving a connection back to a usable access token (refreshing it first if needed).

Connections are per-user, not per-project — an OAuth identity is a personal credential, not a project
resource, so (unlike project_service.role_in_project) there is deliberately no platform-admin bypass
anywhere here: a connection is only ever usable by the user who created it.
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.core import security
from app.models.oauth_connection import OAuthConnection
from app.models.user import User
from app.services.oauth import azure_devops, github

_PROVIDERS = {"github": github, "azure_devops": azure_devops}


def _adapter(provider: str):
    if provider not in _PROVIDERS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown provider")
    return _PROVIDERS[provider]


def build_authorize_url(user: User, provider: str) -> tuple[str, str]:
    state, jti = security.create_oauth_state_token(str(user.id), provider)
    return _adapter(provider).authorize_url(state), jti


async def handle_callback(provider: str, code: str, state: str, cookie_jti: str | None) -> OAuthConnection:
    try:
        claims = security.decode_token(state)
    except security.JWTError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state")
    if claims.get("type") != "oauth_state" or claims.get("provider") != provider:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OAuth state")
    # Binds this callback to the browser that started it — without this, an attacker could send their
    # own authorize_url to a victim and have the victim's approval link the victim's real account to
    # the attacker's ZeroStrike account (state alone only proves it wasn't tampered with, not who's
    # completing it).
    if not cookie_jti or cookie_jti != claims.get("jti"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OAuth session mismatch — please retry")
    user_id = claims["sub"]

    adapter = _adapter(provider)
    token_result = await adapter.exchange_code(code)
    identity = await adapter.fetch_identity(token_result["access_token"])

    now = datetime.now(timezone.utc)
    existing = await OAuthConnection.find_one(
        OAuthConnection.user_id == user_id, OAuthConnection.provider == provider
    )
    access_token_encrypted = security.encrypt_secret(token_result["access_token"])
    refresh_token_encrypted = (
        security.encrypt_secret(token_result["refresh_token"]) if token_result.get("refresh_token") else None
    )
    if existing:
        existing.account_login = identity["account_login"]
        existing.external_account_id = identity["external_account_id"]
        existing.access_token_encrypted = access_token_encrypted
        existing.refresh_token_encrypted = refresh_token_encrypted
        existing.token_expires_at = token_result.get("expires_at")
        existing.scope = token_result.get("scope")
        existing.updated_at = now
        await existing.save()
        return existing

    connection = OAuthConnection(
        user_id=user_id,
        provider=provider,
        account_login=identity["account_login"],
        external_account_id=identity["external_account_id"],
        access_token_encrypted=access_token_encrypted,
        refresh_token_encrypted=refresh_token_encrypted,
        token_expires_at=token_result.get("expires_at"),
        scope=token_result.get("scope"),
        connected_at=now,
        updated_at=now,
    )
    await connection.insert()
    return connection


async def list_connections(user: User) -> list[OAuthConnection]:
    return await OAuthConnection.find(OAuthConnection.user_id == str(user.id)).to_list()


async def get_own_connection_or_404(user: User, provider: str) -> OAuthConnection:
    conn = await OAuthConnection.find_one(
        OAuthConnection.user_id == str(user.id), OAuthConnection.provider == provider
    )
    if not conn:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No connection for this provider")
    return conn


async def disconnect(user: User, provider: str) -> None:
    conn = await get_own_connection_or_404(user, provider)
    await conn.delete()


async def _resolve_access_token(conn: OAuthConnection) -> str:
    """Decrypts the stored access token, refreshing it first (Azure DevOps only — GitHub OAuth App
    tokens don't expire) if it's expired or about to be."""
    near_expiry = conn.token_expires_at and conn.token_expires_at.replace(tzinfo=timezone.utc) < (
        datetime.now(timezone.utc) + timedelta(minutes=2)
    )
    if near_expiry and conn.refresh_token_encrypted:
        refresh_token = security.decrypt_secret(conn.refresh_token_encrypted)
        result = await azure_devops.refresh_access_token(refresh_token)
        conn.access_token_encrypted = security.encrypt_secret(result["access_token"])
        if result.get("refresh_token"):
            conn.refresh_token_encrypted = security.encrypt_secret(result["refresh_token"])
        conn.token_expires_at = result.get("expires_at")
        conn.updated_at = datetime.now(timezone.utc)
        await conn.save()
    return security.decrypt_secret(conn.access_token_encrypted)


async def get_decrypted_token(connection_id: str, user: User) -> tuple[str, str]:
    """Used by scan creation to turn a connection_id into a usable (repo_token, provider) pair —
    the caller needs provider to pick the right git auth scheme (see routers/scans.py). IDOR-safe
    by construction: filters by owner, 404s (never 403s) on a mismatch so a caller can't distinguish
    "doesn't exist" from "not yours." No admin bypass — see module docstring."""
    conn = await OAuthConnection.get(connection_id)
    if not conn or conn.user_id != str(user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return await _resolve_access_token(conn), conn.provider


async def list_repos(user: User, provider: str, *, query: str | None = None, page: int = 1) -> list[dict]:
    conn = await get_own_connection_or_404(user, provider)
    token = await _resolve_access_token(conn)
    return await github.list_repos(token, query, page)


async def list_azure_orgs(user: User) -> list[dict]:
    conn = await get_own_connection_or_404(user, "azure_devops")
    token = await _resolve_access_token(conn)
    return await azure_devops.list_orgs(token, conn.external_account_id)


async def list_azure_projects(user: User, org: str) -> list[dict]:
    conn = await get_own_connection_or_404(user, "azure_devops")
    token = await _resolve_access_token(conn)
    return await azure_devops.list_projects(token, org)


async def list_azure_repos(user: User, org: str, project: str) -> list[dict]:
    conn = await get_own_connection_or_404(user, "azure_devops")
    token = await _resolve_access_token(conn)
    return await azure_devops.list_repos(token, org, project)

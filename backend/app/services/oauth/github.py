"""GitHub OAuth App integration — standard OAuth2, tokens don't expire so no refresh flow.

Repo import auth (git clone) is handled entirely by cloud_scan_service._clone, which already injects
any bearer token via GIT_CONFIG_* env vars — nothing provider-specific needed there.
"""

from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.oauth import OAuthProviderError

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
API_BASE = "https://api.github.com"


def redirect_uri() -> str:
    return f"{settings.backend_public_url}/api/v1/connections/github/callback"


def authorize_url(state: str) -> str:
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": redirect_uri(),
        "scope": "repo read:user",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": redirect_uri(),
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or "access_token" not in body:
        raise OAuthProviderError(f"GitHub token exchange failed: {body.get('error_description', resp.status_code)}")
    return {"access_token": body["access_token"], "scope": body.get("scope")}


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/vnd.github+json"}


async def fetch_identity(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/user", headers=_auth_headers(access_token), timeout=15)
    if resp.status_code != 200:
        raise OAuthProviderError("GitHub identity lookup failed")
    body = resp.json()
    return {"external_account_id": str(body["id"]), "account_login": body["login"]}


async def list_repos(access_token: str, query: str | None, page: int) -> list[dict]:
    params = {
        "affiliation": "owner,collaborator,organization_member",
        "sort": "updated",
        "per_page": "50",
        "page": str(page),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/user/repos", headers=_auth_headers(access_token), params=params, timeout=15
        )
    if resp.status_code != 200:
        raise OAuthProviderError("GitHub repo listing failed")
    repos = resp.json()
    if query:
        repos = [r for r in repos if query.lower() in r["full_name"].lower()]
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "full_name": r["full_name"],
            "clone_url": r["clone_url"],
            "private": r["private"],
            "default_branch": r.get("default_branch"),
        }
        for r in repos
    ]

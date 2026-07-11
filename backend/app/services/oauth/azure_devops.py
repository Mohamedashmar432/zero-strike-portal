"""Azure DevOps OAuth App integration.

Non-standard OAuth2 dialect: both the initial code exchange and the refresh call go through the same
/oauth2/token endpoint with the code/refresh-token passed as `assertion` (not `code`/`refresh_token`),
plus a `client_assertion`/`client_assertion_type` pair carrying the client secret, and `redirect_uri`
resent on both calls. See https://learn.microsoft.com/azure/devops/integrate/get-started/authentication/oauth.

Repos live under Org -> Project -> Repository (no flat "all my repos" endpoint), so the picker needs
three list calls. Git clone auth (Authorization: Bearer <token>) is handled unmodified by
cloud_scan_service._clone.
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.oauth import OAuthProviderError

AUTHORIZE_URL = "https://app.vssps.visualstudio.com/oauth2/authorize"
TOKEN_URL = "https://app.vssps.visualstudio.com/oauth2/token"
VSSPS_BASE = "https://app.vssps.visualstudio.com"
API_VERSION = "7.1"


def redirect_uri() -> str:
    return f"{settings.backend_public_url}/api/v1/connections/azure-devops/callback"


def authorize_url(state: str) -> str:
    params = {
        "client_id": settings.azure_devops_client_id,
        "response_type": "Assertion",
        "scope": "vso.code vso.profile",
        "redirect_uri": redirect_uri(),
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


async def _token_request(grant_type: str, assertion: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
                "client_assertion": settings.azure_devops_client_secret,
                "grant_type": grant_type,
                "assertion": assertion,
                "redirect_uri": redirect_uri(),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    body = resp.json() if resp.content else {}
    if resp.status_code != 200 or "access_token" not in body:
        raise OAuthProviderError(f"Azure DevOps token request failed: {body.get('Message', resp.status_code)}")
    return body


async def exchange_code(code: str) -> dict:
    body = await _token_request("urn:ietf:params:oauth:grant-type:jwt-bearer", code)
    return _to_token_result(body)


async def refresh_access_token(refresh_token: str) -> dict:
    body = await _token_request("refresh_token", refresh_token)
    return _to_token_result(body)


def _to_token_result(body: dict) -> dict:
    expires_in = int(body.get("expires_in", 3600))
    return {
        "access_token": body["access_token"],
        "refresh_token": body.get("refresh_token"),
        "expires_at": datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        "scope": body.get("scope"),
    }


def _auth_headers(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


async def fetch_identity(access_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VSSPS_BASE}/_apis/profile/profiles/me?api-version={API_VERSION}",
            headers=_auth_headers(access_token),
            timeout=15,
        )
    if resp.status_code != 200:
        raise OAuthProviderError("Azure DevOps identity lookup failed")
    body = resp.json()
    return {"external_account_id": body["id"], "account_login": body.get("displayName", body["id"])}


async def list_orgs(access_token: str, member_id: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{VSSPS_BASE}/_apis/accounts",
            headers=_auth_headers(access_token),
            params={"memberId": member_id, "api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise OAuthProviderError("Azure DevOps org listing failed")
    return [{"id": a["accountId"], "name": a["accountName"]} for a in resp.json().get("value", [])]


async def list_projects(access_token: str, org: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://dev.azure.com/{org}/_apis/projects",
            headers=_auth_headers(access_token),
            params={"api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise OAuthProviderError("Azure DevOps project listing failed")
    return [{"id": p["id"], "name": p["name"]} for p in resp.json().get("value", [])]


async def list_repos(access_token: str, org: str, project: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://dev.azure.com/{org}/{project}/_apis/git/repositories",
            headers=_auth_headers(access_token),
            params={"api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise OAuthProviderError("Azure DevOps repo listing failed")
    repos = resp.json().get("value", [])
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "full_name": f"{project}/{r['name']}",
            "clone_url": r["remoteUrl"],
            "private": True,  # Azure DevOps repos are org-private by default; no public-repo concept surfaced here
            "default_branch": (r.get("defaultBranch") or "").removeprefix("refs/heads/") or None,
        }
        for r in repos
    ]

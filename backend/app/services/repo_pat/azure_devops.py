"""Azure DevOps REST calls authenticated with a user-supplied Personal Access Token (PAT).

Uses Basic auth (base64(":"+pat)) — NOT the Bearer scheme services/oauth/azure_devops.py uses for
OAuth access tokens. Azure DevOps PATs and OAuth access tokens are not interchangeable; reusing the
Bearer-based OAuth adapter here would silently 401 on every call. Mirrors zero-strike-cli's
AzureDevOpsIntegration (GET .../_apis/git/repositories, GET .../refs?filter=heads).
"""

import base64

import httpx

from app.services.repo_pat import RepoPatError

API_VERSION = "7.0"


def _auth_headers(pat: str) -> dict:
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def list_repos(pat: str, org: str, project: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://dev.azure.com/{org}/{project}/_apis/git/repositories",
            headers=_auth_headers(pat),
            params={"api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise RepoPatError("Azure DevOps repo listing failed — check the PAT, organization, and project name")
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


async def list_branches(pat: str, org: str, project: str, repo_id: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}/refs",
            headers=_auth_headers(pat),
            params={"filter": "heads/", "api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise RepoPatError("Azure DevOps branch listing failed")
    refs = resp.json().get("value", [])
    return [{"name": r["name"].removeprefix("refs/heads/")} for r in refs]

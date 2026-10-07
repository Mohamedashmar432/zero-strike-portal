"""Azure DevOps REST calls authenticated with a user-supplied Personal Access Token (PAT).

Uses Basic auth (base64(":"+pat)) — NOT the Bearer scheme services/oauth/azure_devops.py uses for
OAuth access tokens. Azure DevOps PATs and OAuth access tokens are not interchangeable; reusing the
Bearer-based OAuth adapter here would silently 401 on every call. Mirrors zero-strike-cli's
AzureDevOpsIntegration (GET .../_apis/git/repositories, GET .../refs?filter=heads).
"""

import base64
from urllib.parse import quote

import httpx

from app.services.repo_pat import RepoPatError

API_VERSION = "7.0"


def _auth_headers(pat: str) -> dict:
    token = base64.b64encode(f":{pat}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _base(org: str, project: str | None = None) -> str:
    # Project names may contain spaces and other URL-significant characters.
    url = f"https://dev.azure.com/{quote(org, safe='')}"
    return f"{url}/{quote(project, safe='')}" if project else url


PROJECT_PAGE_SIZE = 500
# ponytail: 500 x 20 = 10k projects, then we stop — far past any real org.
MAX_PROJECT_PAGES = 20


async def list_projects(pat: str, org: str) -> list[dict]:
    """Every project in the org this PAT can see, following ADO's continuation-token paging."""
    projects: list[dict] = []
    token: str | None = None
    async with httpx.AsyncClient() as client:
        for _ in range(MAX_PROJECT_PAGES):
            params = {"$top": str(PROJECT_PAGE_SIZE), "api-version": API_VERSION}
            if token:
                params["continuationToken"] = token
            resp = await client.get(
                f"{_base(org)}/_apis/projects", headers=_auth_headers(pat), params=params, timeout=15
            )
            # ADO answers a bad PAT with a 203 sign-in page, not a 401 — anything but 200 is a failure.
            if resp.status_code != 200:
                raise RepoPatError(
                    "Azure DevOps project listing failed — check the organization name and that the PAT "
                    "has Project and Team (Read) and Code (Read) scopes"
                )
            projects.extend(
                {"id": p["id"], "name": p["name"], "description": p.get("description")}
                for p in resp.json().get("value", [])
            )
            token = resp.headers.get("x-ms-continuationtoken")
            if not token:
                break
    return sorted(projects, key=lambda p: p["name"].lower())


async def list_repos(pat: str, org: str, project: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{_base(org, project)}/_apis/git/repositories",
            headers=_auth_headers(pat),
            params={"api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise RepoPatError("Azure DevOps repo listing failed — check the PAT, organization, and project name")
    repos = sorted(resp.json().get("value", []), key=lambda r: r["name"].lower())
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
            f"{_base(org, project)}/_apis/git/repositories/{quote(repo_id, safe='')}/refs",
            headers=_auth_headers(pat),
            params={"filter": "heads/", "api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise RepoPatError("Azure DevOps branch listing failed")
    refs = resp.json().get("value", [])
    return [{"name": r["name"].removeprefix("refs/heads/")} for r in refs]

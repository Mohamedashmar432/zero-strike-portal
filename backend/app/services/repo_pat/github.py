"""GitHub REST calls authenticated with a user-supplied Personal Access Token (PAT) — not OAuth.

Mirrors zero-strike-cli's GitHubIntegration (GET /user/repos, GET /repos/{owner}/{repo}/branches), so
a PAT that already works with that CLI works here unchanged. Independent of services/oauth/github.py
by design: that module authenticates with an OAuth App access token on a different credential
lifecycle (exchange/refresh) — this one only ever sees a raw PAT, and the two must not be merged.
"""

import httpx

from app.services.repo_pat import RepoPatError

API_BASE = "https://api.github.com"


def _auth_headers(pat: str) -> dict:
    return {
        "Authorization": f"Bearer {pat}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def list_repos(pat: str, query: str | None = None, page: int = 1) -> list[dict]:
    params = {
        "affiliation": "owner,collaborator,organization_member",
        "sort": "updated",
        "per_page": "50",
        "page": str(page),
    }
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/user/repos", headers=_auth_headers(pat), params=params, timeout=15)
    if resp.status_code != 200:
        raise RepoPatError("GitHub repo listing failed — check the PAT has 'repo' scope")
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


async def list_branches(pat: str, owner: str, repo: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/repos/{owner}/{repo}/branches", headers=_auth_headers(pat), timeout=15)
    if resp.status_code != 200:
        raise RepoPatError("GitHub branch listing failed")
    return [{"name": b["name"]} for b in resp.json()]


async def fetch_public_repo(owner: str, repo: str) -> dict:
    """Unauthenticated lookup, used to connect a public repo to a project with no PAT at all. Raises
    RepoPatError if the repo doesn't exist or (the actual safety check, since anyone could claim a
    private repo is public) isn't actually public -- private repos 404 on this unauthenticated call."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/repos/{owner}/{repo}", timeout=15)
    if resp.status_code != 200:
        raise RepoPatError("Repository not found or not public — private repos need a Personal Access Token")
    body = resp.json()
    return {
        "id": str(body["id"]),
        "name": body["name"],
        "full_name": body["full_name"],
        "clone_url": body["clone_url"],
        "private": body["private"],
        "default_branch": body.get("default_branch"),
    }


async def list_public_branches(owner: str, repo: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/repos/{owner}/{repo}/branches", timeout=15)
    if resp.status_code != 200:
        raise RepoPatError("GitHub branch listing failed")
    return [{"name": b["name"]} for b in resp.json()]

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


BRANCH_PAGE_SIZE = 100  # GitHub's maximum
# ponytail: 100 x 20 = 2000 branches, then we stop. Raise it (or switch the picker to a
# server-side prefix search via /git/matching-refs/heads/) only if a real repo overflows.
MAX_BRANCH_PAGES = 20


async def _fetch_branches(owner: str, repo: str, headers: dict) -> list[dict]:
    """Walks every page — GitHub defaults to 30 branches per page, which silently truncated
    the picker on any repo with more than that."""
    names: list[str] = []
    async with httpx.AsyncClient() as client:
        for page in range(1, MAX_BRANCH_PAGES + 1):
            resp = await client.get(
                f"{API_BASE}/repos/{owner}/{repo}/branches",
                headers=headers,
                params={"per_page": str(BRANCH_PAGE_SIZE), "page": str(page)},
                timeout=15,
            )
            if resp.status_code != 200:
                raise RepoPatError("GitHub branch listing failed")
            batch = resp.json()
            names.extend(b["name"] for b in batch)
            if len(batch) < BRANCH_PAGE_SIZE:
                break
    return [{"name": n} for n in names]


async def list_branches(pat: str, owner: str, repo: str) -> list[dict]:
    return await _fetch_branches(owner, repo, _auth_headers(pat))


async def fetch_repo(pat: str, owner: str, repo: str) -> dict:
    """Look up one repo by name with a PAT — the "paste the URL + a token" connect flow, which
    skips /user/repos entirely (that listing only returns a page at a time, so a repo outside the
    50 most-recently-updated was unreachable through the picker)."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{API_BASE}/repos/{owner}/{repo}", headers=_auth_headers(pat), timeout=15)
    if resp.status_code == 404:
        # 404 is also what GitHub returns for a repo the token simply can't see, so say both.
        raise RepoPatError(f"{owner}/{repo} not found, or this token can't access it")
    if resp.status_code != 200:
        raise RepoPatError("GitHub rejected this token — check it hasn't expired and has repo access")
    body = resp.json()
    return {
        "id": str(body["id"]),
        "name": body["name"],
        "full_name": body["full_name"],
        "clone_url": body["clone_url"],
        "private": body["private"],
        "default_branch": body.get("default_branch"),
    }


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
    return await _fetch_branches(owner, repo, {})

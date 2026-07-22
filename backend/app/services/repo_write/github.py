"""GitHub PR creation for AI Auto-Fix. Branch/commit/push are done via the local git CLI
(git_workspace); only the pull-request itself needs REST. Uses Bearer auth (GitHub REST), distinct
from the Basic scheme git-over-HTTPS uses for the push -- see repo_pat/github.py + Scan.repo_token_auth_scheme.
The `repo` OAuth scope / a classic `repo` PAT already grants both push and PR, so no scope widening."""

import httpx

from app.services.repo_write import RepoWriteError

API_BASE = "https://api.github.com"


def _msg(resp: httpx.Response) -> str:
    try:
        return resp.json().get("message", str(resp.status_code))
    except Exception:
        return str(resp.status_code)


async def open_pull_request(
    token: str, owner: str, repo: str, *, head: str, base: str, title: str, body: str
) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{API_BASE}/repos/{owner}/{repo}/pulls",
            headers=headers,
            json={"title": title, "head": head, "base": base, "body": body},
            timeout=30,
        )
    if resp.status_code not in (200, 201):
        raise RepoWriteError(f"GitHub PR creation failed ({resp.status_code}): {_msg(resp)}")
    b = resp.json()
    return {"pr_url": b["html_url"], "pr_number": b["number"]}

"""GitHub PR creation for AI Auto-Fix. Branch/commit/push are done via the local git CLI
(git_workspace); only the pull-request itself needs REST. Uses Bearer auth (GitHub REST), distinct
from the Basic scheme git-over-HTTPS uses for the push -- see repo_pat/github.py + Scan.repo_token_auth_scheme.
The `repo` OAuth scope / a classic `repo` PAT already grants both push and PR, so no scope widening."""

from urllib.parse import quote

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


async def get_pull_request_state(token: str | None, owner: str, repo: str, number: int) -> dict:
    """Read one PR's state (docs/CLONE_LIFECYCLE_AND_SCAN_REUSE.md, phase D). Read-only, so it uses the
    repo's read credential; a public repo connected without one is read anonymously. The token only
    ever travels in the Authorization header. Returns {state: open|merged|closed, merged_at,
    merge_commit}."""
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{API_BASE}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/pulls/{int(number)}",
            headers=headers,
            timeout=15,
        )
    if resp.status_code != 200:
        raise RepoWriteError(f"GitHub PR lookup failed ({resp.status_code}): {_msg(resp)}")
    b = resp.json()
    if b.get("merged") or b.get("merged_at"):
        state = "merged"
    else:
        state = "open" if b.get("state") == "open" else "closed"
    return {
        "state": state,
        "merged_at": b.get("merged_at") if state == "merged" else None,
        "merge_commit": b.get("merge_commit_sha") if state == "merged" else None,
    }

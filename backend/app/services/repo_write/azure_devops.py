"""Azure DevOps PR creation for AI Auto-Fix. ProjectRepo stores repo_full_name/org/project but not
the repository GUID, so resolve it by name at apply time. PAT -> Basic auth; OAuth AAD token ->
Bearer (matches repo_pat vs oauth adapters). Requires the vso.code_write scope (see oauth/azure_devops.py)."""

import base64
from urllib.parse import quote

import httpx

from app.services.repo_write import RepoWriteError

API_VERSION = "7.1"


def _headers(token: str, auth_scheme: str) -> dict:
    if auth_scheme == "basic":
        return {"Authorization": f"Basic {base64.b64encode(f':{token}'.encode()).decode()}"}
    return {"Authorization": f"Bearer {token}"}


def _msg(resp: httpx.Response) -> str:
    try:
        return resp.json().get("message", str(resp.status_code))
    except Exception:
        return str(resp.status_code)


async def resolve_repo_id(token: str, auth_scheme: str, org: str, project: str, repo_name: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_name}",
            headers=_headers(token, auth_scheme),
            params={"api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise RepoWriteError(f"Azure DevOps repo lookup failed ({resp.status_code}): {_msg(resp)}")
    return resp.json()["id"]


async def open_pull_request(
    token: str,
    auth_scheme: str,
    org: str,
    project: str,
    repo_id: str,
    *,
    source_branch: str,
    target_branch: str,
    title: str,
    description: str,
) -> dict:
    body = {
        "sourceRefName": f"refs/heads/{source_branch}",
        "targetRefName": f"refs/heads/{target_branch}",
        "title": title,
        "description": description,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo_id}/pullrequests",
            headers={**_headers(token, auth_scheme), "Content-Type": "application/json"},
            params={"api-version": API_VERSION},
            json=body,
            timeout=30,
        )
    if resp.status_code not in (200, 201):
        raise RepoWriteError(f"Azure DevOps PR creation failed ({resp.status_code}): {_msg(resp)}")
    b = resp.json()
    pr_id = b["pullRequestId"]
    web = (b.get("repository") or {}).get("webUrl") or ""
    pr_url = f"{web}/pullrequest/{pr_id}" if web else ((b.get("_links") or {}).get("web") or {}).get("href", "")
    return {"pr_url": pr_url, "pr_number": pr_id}


# Azure DevOps PR status -> the portal's open|merged|closed. "completed" is a merge; "abandoned" is a
# close without one.
_ADO_STATE = {"active": "open", "completed": "merged", "abandoned": "closed"}


async def get_pull_request_state(token: str, auth_scheme: str, org: str, project: str, pr_id: int) -> dict:
    """Read one PR's state by id at the project scope (a PR id is unique within an ADO project, so no
    repository GUID lookup is needed). Token in the Authorization header only. Returns {state,
    merged_at, merge_commit}."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://dev.azure.com/{quote(org, safe='')}/{quote(project, safe='')}"
            f"/_apis/git/pullrequests/{int(pr_id)}",
            headers=_headers(token, auth_scheme),
            params={"api-version": API_VERSION},
            timeout=15,
        )
    if resp.status_code != 200:
        raise RepoWriteError(f"Azure DevOps PR lookup failed ({resp.status_code}): {_msg(resp)}")
    b = resp.json()
    state = _ADO_STATE.get(str(b.get("status") or "").lower(), "open")
    return {
        "state": state,
        "merged_at": b.get("closedDate") if state == "merged" else None,
        "merge_commit": ((b.get("lastMergeCommit") or {}).get("commitId")) if state == "merged" else None,
    }

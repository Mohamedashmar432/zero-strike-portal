import asyncio
import base64
from types import SimpleNamespace

import pytest

from app.services.repo_pat import RepoPatError
from app.services.repo_pat import github as gh
from app.services.repo_pat.azure_devops import _auth_headers as ado_auth_headers
from app.services.repo_pat.github import _auth_headers as gh_auth_headers


def test_github_auth_headers_use_bearer():
    headers = gh_auth_headers("my-pat")
    assert headers["Authorization"] == "Bearer my-pat"


def test_azure_devops_auth_headers_use_basic_not_bearer():
    """Azure DevOps PATs authenticate with HTTP Basic (empty username, PAT as password) — never
    Bearer. Reusing the OAuth adapter's Bearer scheme here is exactly the bug that prompted a
    dedicated PAT-auth module: regression test pinning the header format down explicitly."""
    headers = ado_auth_headers("my-pat")
    expected = base64.b64encode(b":my-pat").decode()
    assert headers["Authorization"] == f"Basic {expected}"
    assert "Bearer" not in headers["Authorization"]


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """Serves a repo with `total` branches, 100 per page, recording the pages asked for."""

    def __init__(self, total, calls):
        self._total = total
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        page = int(kwargs["params"]["page"])
        size = int(kwargs["params"]["per_page"])
        self._calls.append(page)
        start = (page - 1) * size
        return _FakeResponse([{"name": f"branch-{i}"} for i in range(start, min(start + size, self._total))])


def test_github_branch_listing_pages_past_githubs_default_page(monkeypatch):
    """GitHub returns 30 branches per page unless asked otherwise, which quietly truncated the
    branch picker. A 412-branch repo must come back whole, not as its first page."""
    calls: list[int] = []
    monkeypatch.setattr(gh, "httpx", SimpleNamespace(AsyncClient=lambda: _FakeClient(412, calls)))

    branches = asyncio.run(gh.list_branches("pat", "acme", "widgets"))

    assert len(branches) == 412
    assert branches[0]["name"] == "branch-0"
    assert branches[-1]["name"] == "branch-411"
    assert calls == [1, 2, 3, 4, 5]  # stops on the short page, no extra request


def test_github_branch_listing_stops_at_the_page_cap(monkeypatch):
    """A repo with more branches than we page for is truncated deliberately, not looped forever."""
    calls: list[int] = []
    monkeypatch.setattr(gh, "httpx", SimpleNamespace(AsyncClient=lambda: _FakeClient(10_000, calls)))

    branches = asyncio.run(gh.list_branches("pat", "acme", "widgets"))

    assert len(branches) == gh.MAX_BRANCH_PAGES * gh.BRANCH_PAGE_SIZE
    assert len(calls) == gh.MAX_BRANCH_PAGES


def test_github_branch_listing_surfaces_a_failure_on_a_later_page(monkeypatch):
    """Paging turns one request into many, so a mid-walk failure (rate limit, revoked token) must
    raise rather than quietly return the pages fetched so far as if they were the whole repo."""

    class _FailsOnPageTwo(_FakeClient):
        async def get(self, url, **kwargs):
            if int(kwargs["params"]["page"]) == 2:
                return SimpleNamespace(status_code=403, json=lambda: {})
            return await super().get(url, **kwargs)

    monkeypatch.setattr(gh, "httpx", SimpleNamespace(AsyncClient=lambda: _FailsOnPageTwo(500, [])))

    with pytest.raises(RepoPatError):
        asyncio.run(gh.list_branches("pat", "acme", "widgets"))


def test_azure_devops_project_listing_follows_continuation_token_and_encodes_names(monkeypatch):
    """An org can hold more projects than one page; the walk must follow x-ms-continuationtoken
    to the end, and a project name with a space must reach the URL encoded, not split the path."""
    from app.services.repo_pat import azure_devops as ado

    pages = {
        None: ([{"id": "2", "name": "beta"}, {"id": "1", "name": "Alpha"}], "tok-2"),
        "tok-2": ([{"id": "3", "name": "Gamma Team"}], None),
    }
    seen: list = []

    class _Client(_FakeClient):
        async def get(self, url, **kwargs):
            token = kwargs["params"].get("continuationToken")
            seen.append((url, token))
            value, nxt = pages[token]
            return SimpleNamespace(
                status_code=200,
                json=lambda: {"value": value},
                headers={"x-ms-continuationtoken": nxt} if nxt else {},
            )

    monkeypatch.setattr(ado, "httpx", SimpleNamespace(AsyncClient=lambda: _Client(0, [])))
    projects = asyncio.run(ado.list_projects("pat", "my org"))

    assert [p["name"] for p in projects] == ["Alpha", "beta", "Gamma Team"]  # sorted, case-insensitive
    assert [t for _, t in seen] == [None, "tok-2"]
    assert seen[0][0] == "https://dev.azure.com/my%20org/_apis/projects"
    assert ado._base("org", "Gamma Team") == "https://dev.azure.com/org/Gamma%20Team"


def test_azure_devops_bad_pat_sign_in_page_is_a_failure(monkeypatch):
    """ADO answers an invalid PAT with a 203 HTML sign-in page — it must not parse as zero projects."""
    from app.services.repo_pat import azure_devops as ado

    class _Client(_FakeClient):
        async def get(self, url, **kwargs):
            return SimpleNamespace(status_code=203, json=lambda: {}, headers={})

    monkeypatch.setattr(ado, "httpx", SimpleNamespace(AsyncClient=lambda: _Client(0, [])))
    with pytest.raises(RepoPatError):
        asyncio.run(ado.list_projects("bad", "org"))

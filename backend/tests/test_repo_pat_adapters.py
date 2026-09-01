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

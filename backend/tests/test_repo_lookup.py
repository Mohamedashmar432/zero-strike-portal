"""The URL + one-off PAT lookup (routers/repo_lookup.py) — repo and branches in one POST."""

from app.routers import repo_lookup
from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _patch_github(monkeypatch, seen: dict):
    async def _fake_fetch_repo(pat, owner, repo):
        seen.update(pat=pat, owner=owner, repo=repo)
        return {
            "id": "1",
            "name": repo,
            "full_name": f"{owner}/{repo}",
            "clone_url": f"https://github.com/{owner}/{repo}.git",
            "private": True,
            "default_branch": "main",
        }

    async def _fake_list_branches(pat, owner, repo):
        return [{"name": "main"}, {"name": "develop"}]

    monkeypatch.setattr(repo_lookup.github, "fetch_repo", _fake_fetch_repo)
    monkeypatch.setattr(repo_lookup.github, "list_branches", _fake_list_branches)


def test_lookup_returns_private_repo_and_branches(client, monkeypatch):
    seen: dict = {}
    _patch_github(monkeypatch, seen)
    user = register_and_login(client, email="lookup1@zerostrike.dev")

    r = client.post(
        "/api/v1/repo-lookup/github",
        json={"repo_full_name": "acme-org/private-api", "pat": "ghp_x"},
        headers=_headers(user),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Unlike the public lookup, a private repo is the expected case here, not a rejection.
    assert body["repo"]["full_name"] == "acme-org/private-api"
    assert body["repo"]["private"] is True
    assert [b["name"] for b in body["branches"]] == ["main", "develop"]
    assert seen == {"pat": "ghp_x", "owner": "acme-org", "repo": "private-api"}


def test_lookup_rejects_a_name_that_is_not_owner_slash_repo(client, monkeypatch):
    _patch_github(monkeypatch, {})
    user = register_and_login(client, email="lookup2@zerostrike.dev")
    r = client.post(
        "/api/v1/repo-lookup/github",
        json={"repo_full_name": "just-a-repo", "pat": "ghp_x"},
        headers=_headers(user),
    )
    assert r.status_code == 400


def test_lookup_requires_a_signed_in_user(client):
    # The PAT is the caller's, but this endpoint still must not be an open proxy to GitHub.
    r = client.post("/api/v1/repo-lookup/github", json={"repo_full_name": "a/b", "pat": "ghp_x"})
    assert r.status_code == 401

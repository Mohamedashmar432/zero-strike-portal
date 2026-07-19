from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_get_public_repo_returns_metadata(client, monkeypatch):
    from app.services.repo_pat import github

    async def _fake_fetch_public_repo(owner, repo):
        assert (owner, repo) == ("octocat", "hello-world")
        return {
            "id": "1",
            "name": "hello-world",
            "full_name": "octocat/hello-world",
            "clone_url": "https://github.com/octocat/hello-world.git",
            "private": False,
            "default_branch": "main",
        }

    monkeypatch.setattr(github, "fetch_public_repo", _fake_fetch_public_repo)

    owner = register_and_login(client, email="pubrepo1@zerostrike.dev")
    r = client.get("/api/v1/public-repos/github/octocat/hello-world", headers=_headers(owner))
    assert r.status_code == 200
    body = r.json()
    assert body["full_name"] == "octocat/hello-world"
    assert body["private"] is False


def test_get_public_repo_rejects_private_repo(client, monkeypatch):
    from app.services.repo_pat import github

    async def _fake_fetch_public_repo(owner, repo):
        return {
            "id": "1",
            "name": "secret",
            "full_name": "octocat/secret",
            "clone_url": "https://github.com/octocat/secret.git",
            "private": True,
            "default_branch": "main",
        }

    monkeypatch.setattr(github, "fetch_public_repo", _fake_fetch_public_repo)

    owner = register_and_login(client, email="pubrepo2@zerostrike.dev")
    r = client.get("/api/v1/public-repos/github/octocat/secret", headers=_headers(owner))
    assert r.status_code == 400


def test_get_public_repo_not_found(client, monkeypatch):
    from app.services.repo_pat import RepoPatError, github

    async def _fake_fetch_public_repo(owner, repo):
        raise RepoPatError("Repository not found or not public — private repos need a Personal Access Token")

    monkeypatch.setattr(github, "fetch_public_repo", _fake_fetch_public_repo)

    owner = register_and_login(client, email="pubrepo3@zerostrike.dev")
    r = client.get("/api/v1/public-repos/github/octocat/does-not-exist", headers=_headers(owner))
    assert r.status_code == 400


def test_get_public_repo_branches(client, monkeypatch):
    from app.services.repo_pat import github

    async def _fake_list_public_branches(owner, repo):
        return [{"name": "main"}, {"name": "develop"}]

    monkeypatch.setattr(github, "list_public_branches", _fake_list_public_branches)

    owner = register_and_login(client, email="pubrepo4@zerostrike.dev")
    r = client.get("/api/v1/public-repos/github/octocat/hello-world/branches", headers=_headers(owner))
    assert r.status_code == 200
    assert [b["name"] for b in r.json()] == ["main", "develop"]


def test_public_repo_lookup_requires_auth(client):
    r = client.get("/api/v1/public-repos/github/octocat/hello-world")
    assert r.status_code == 401

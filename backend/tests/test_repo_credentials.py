from app.core import security
from app.services.repo_pat import RepoPatError, azure_devops, github
from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def _fake_github_list_repos(pat, query=None, page=1):
    return [
        {
            "id": "1",
            "name": "repo",
            "full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "private": False,
            "default_branch": "main",
        }
    ]


async def _fake_azure_list_repos(pat, org, project):
    return [
        {
            "id": "guid-1",
            "name": "repo",
            "full_name": f"{project}/repo",
            "clone_url": f"https://dev.azure.com/{org}/{project}/_git/repo",
            "private": True,
            "default_branch": "main",
        }
    ]


def test_create_github_credential_validates_and_stores_encrypted(client, monkeypatch):
    monkeypatch.setattr(github, "list_repos", _fake_github_list_repos)
    owner = register_and_login(client, email="pat1@zerostrike.dev")

    r = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "github", "pat": "ghp_secret", "organization": "octocat", "label": "Personal"},
        headers=_headers(owner),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "github"
    assert body["organization"] == "octocat"
    assert body["label"] == "Personal"
    assert "pat" not in body
    assert "pat_encrypted" not in body

    async def _check():
        from app.models.repo_credential import RepoCredential

        credential = await RepoCredential.get(body["id"])
        assert credential.pat_encrypted != "ghp_secret"
        assert security.decrypt_secret(credential.pat_encrypted) == "ghp_secret"

    import asyncio

    asyncio.run(_check())


def test_create_azure_devops_credential_requires_ado_project(client):
    owner = register_and_login(client, email="pat2@zerostrike.dev")
    r = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "azure_devops", "pat": "ado-pat", "organization": "myorg"},
        headers=_headers(owner),
    )
    assert r.status_code == 422


def test_create_credential_bad_pat_is_400(client, monkeypatch):
    async def _fails(pat, query=None, page=1):
        raise RepoPatError("GitHub repo listing failed — check the PAT has 'repo' scope")

    monkeypatch.setattr(github, "list_repos", _fails)
    owner = register_and_login(client, email="pat3@zerostrike.dev")

    r = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "github", "pat": "bad", "organization": "octocat"},
        headers=_headers(owner),
    )
    assert r.status_code == 400


def test_list_and_delete_credential(client, monkeypatch):
    monkeypatch.setattr(github, "list_repos", _fake_github_list_repos)
    owner = register_and_login(client, email="pat4@zerostrike.dev")
    created = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "github", "pat": "ghp_secret", "organization": "octocat"},
        headers=_headers(owner),
    ).json()

    listed = client.get("/api/v1/repo-credentials", headers=_headers(owner)).json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]

    r = client.delete(f"/api/v1/repo-credentials/{created['id']}", headers=_headers(owner))
    assert r.status_code == 204
    assert client.get("/api/v1/repo-credentials", headers=_headers(owner)).json() == []


def test_credential_from_other_user_is_404(client, monkeypatch):
    monkeypatch.setattr(github, "list_repos", _fake_github_list_repos)
    owner_a = register_and_login(client, email="pat5a@zerostrike.dev")
    created = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "github", "pat": "ghp_secret", "organization": "octocat"},
        headers=_headers(owner_a),
    ).json()

    owner_b = register_and_login(client, email="pat5b@zerostrike.dev")
    r = client.get(f"/api/v1/repo-credentials/{created['id']}/repos", headers=_headers(owner_b))
    assert r.status_code == 404
    r = client.delete(f"/api/v1/repo-credentials/{created['id']}", headers=_headers(owner_b))
    assert r.status_code == 404


def test_list_repos_and_branches_github(client, monkeypatch):
    monkeypatch.setattr(github, "list_repos", _fake_github_list_repos)

    async def _fake_branches(pat, owner, repo):
        assert owner == "octocat"
        assert repo == "repo"
        return [{"name": "main"}, {"name": "dev"}]

    monkeypatch.setattr(github, "list_branches", _fake_branches)

    owner = register_and_login(client, email="pat6@zerostrike.dev")
    credential = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "github", "pat": "ghp_secret", "organization": "octocat"},
        headers=_headers(owner),
    ).json()

    repos = client.get(f"/api/v1/repo-credentials/{credential['id']}/repos", headers=_headers(owner)).json()
    assert repos == [
        {
            "id": "1",
            "name": "repo",
            "full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "private": False,
            "default_branch": "main",
        }
    ]

    branches = client.get(
        f"/api/v1/repo-credentials/{credential['id']}/repos/octocat/repo/branches", headers=_headers(owner)
    ).json()
    assert branches == [{"name": "main"}, {"name": "dev"}]


def test_list_repos_and_branches_azure_devops(client, monkeypatch):
    monkeypatch.setattr(azure_devops, "list_repos", _fake_azure_list_repos)

    async def _fake_ado_branches(pat, org, project, repo_id):
        assert org == "myorg"
        assert project == "myproj"
        assert repo_id == "guid-1"
        return [{"name": "main"}]

    monkeypatch.setattr(azure_devops, "list_branches", _fake_ado_branches)

    owner = register_and_login(client, email="pat7@zerostrike.dev")
    credential = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "azure_devops", "pat": "ado-pat", "organization": "myorg", "ado_project": "myproj"},
        headers=_headers(owner),
    ).json()

    repos = client.get(f"/api/v1/repo-credentials/{credential['id']}/repos", headers=_headers(owner)).json()
    assert repos[0]["full_name"] == "myproj/repo"

    branches = client.get(
        f"/api/v1/repo-credentials/{credential['id']}/repos/guid-1/branches", headers=_headers(owner)
    ).json()
    assert branches == [{"name": "main"}]

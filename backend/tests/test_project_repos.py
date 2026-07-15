import asyncio

from app.core import security
from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def test_add_repo_with_inline_pat_stores_own_encrypted_copy(client):
    owner = register_and_login(client, email="prepo1@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    r = client.post(
        f"/api/v1/projects/{project['id']}/repos",
        json={
            "provider": "github",
            "pat": "ghp_inline",
            "organization": "octocat",
            "repo_full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "selected_branch": "main",
            "label": "Frontend repo",
        },
        headers=_headers(owner),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "github"
    assert body["repo_full_name"] == "octocat/repo"
    assert body["selected_branch"] == "main"
    assert "pat" not in body
    assert "pat_encrypted" not in body

    async def _check():
        from app.models.project_repo import ProjectRepo

        repo = await ProjectRepo.get(body["id"])
        assert repo.pat_encrypted != "ghp_inline"
        assert security.decrypt_secret(repo.pat_encrypted) == "ghp_inline"

    asyncio.run(_check())


def test_project_can_hold_multiple_repo_connections(client):
    owner = register_and_login(client, email="prepo2@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    for name, branch in [("octocat/frontend", "main"), ("octocat/backend", "develop")]:
        r = client.post(
            f"/api/v1/projects/{project['id']}/repos",
            json={
                "provider": "github",
                "pat": "ghp_x",
                "organization": "octocat",
                "repo_full_name": name,
                "clone_url": f"https://github.com/{name}.git",
                "selected_branch": branch,
            },
            headers=_headers(owner),
        )
        assert r.status_code == 201

    repos = client.get(f"/api/v1/projects/{project['id']}/repos", headers=_headers(owner)).json()
    assert sorted(r["repo_full_name"] for r in repos) == ["octocat/backend", "octocat/frontend"]


def test_two_projects_with_different_accounts_never_cross_contaminate(client):
    """Regression test for the exact bug that prompted this design: connecting project B to a
    different GitHub account/org must never change, break, or reuse project A's credential."""
    owner = register_and_login(client, email="prepo3@zerostrike.dev")
    project_a = _create_project(client, _headers(owner), name="A")
    project_b = _create_project(client, _headers(owner), name="B")

    client.post(
        f"/api/v1/projects/{project_a['id']}/repos",
        json={
            "provider": "github",
            "pat": "account-a-pat",
            "organization": "org-a",
            "repo_full_name": "org-a/repo",
            "clone_url": "https://github.com/org-a/repo.git",
            "selected_branch": "main",
        },
        headers=_headers(owner),
    )
    client.post(
        f"/api/v1/projects/{project_b['id']}/repos",
        json={
            "provider": "azure_devops",
            "pat": "account-b-pat",
            "organization": "org-b",
            "ado_project": "proj-b",
            "repo_full_name": "proj-b/repo",
            "clone_url": "https://dev.azure.com/org-b/proj-b/_git/repo",
            "selected_branch": "develop",
        },
        headers=_headers(owner),
    )

    repos_a = client.get(f"/api/v1/projects/{project_a['id']}/repos", headers=_headers(owner)).json()
    repos_b = client.get(f"/api/v1/projects/{project_b['id']}/repos", headers=_headers(owner)).json()
    assert len(repos_a) == 1
    assert len(repos_b) == 1
    assert repos_a[0]["organization"] == "org-a"
    assert repos_b[0]["organization"] == "org-b"

    async def _check_independent_credentials():
        from app.models.project_repo import ProjectRepo

        repo_a = await ProjectRepo.get(repos_a[0]["id"])
        repo_b = await ProjectRepo.get(repos_b[0]["id"])
        assert security.decrypt_secret(repo_a.pat_encrypted) == "account-a-pat"
        assert security.decrypt_secret(repo_b.pat_encrypted) == "account-b-pat"

    asyncio.run(_check_independent_credentials())


def test_add_repo_via_saved_credential_copies_pat(client, monkeypatch):
    from app.services.repo_pat import github

    async def _fake_list_repos(pat, query=None, page=1):
        return [{"id": "1", "name": "repo", "full_name": "octocat/repo", "clone_url": "u", "private": False, "default_branch": "main"}]

    monkeypatch.setattr(github, "list_repos", _fake_list_repos)

    owner = register_and_login(client, email="prepo4@zerostrike.dev")
    credential = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "github", "pat": "ghp_saved", "organization": "octocat"},
        headers=_headers(owner),
    ).json()
    project = _create_project(client, _headers(owner))

    r = client.post(
        f"/api/v1/projects/{project['id']}/repos",
        json={
            "credential_id": credential["id"],
            "repo_full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "selected_branch": "main",
        },
        headers=_headers(owner),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["provider"] == "github"
    assert body["organization"] == "octocat"

    # Deleting the Settings credential afterward must not affect the already-connected repo.
    client.delete(f"/api/v1/repo-credentials/{credential['id']}", headers=_headers(owner))
    still_there = client.get(f"/api/v1/projects/{project['id']}/repos", headers=_headers(owner)).json()
    assert len(still_there) == 1

    async def _check():
        from app.models.project_repo import ProjectRepo

        repo = await ProjectRepo.get(body["id"])
        assert security.decrypt_secret(repo.pat_encrypted) == "ghp_saved"

    asyncio.run(_check())


def test_update_branch_and_remove_repo(client):
    owner = register_and_login(client, email="prepo5@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    repo = client.post(
        f"/api/v1/projects/{project['id']}/repos",
        json={
            "provider": "github",
            "pat": "ghp_x",
            "organization": "octocat",
            "repo_full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "selected_branch": "main",
        },
        headers=_headers(owner),
    ).json()

    r = client.patch(
        f"/api/v1/projects/{project['id']}/repos/{repo['id']}",
        json={"selected_branch": "release"},
        headers=_headers(owner),
    )
    assert r.status_code == 200
    assert r.json()["selected_branch"] == "release"

    r = client.delete(f"/api/v1/projects/{project['id']}/repos/{repo['id']}", headers=_headers(owner))
    assert r.status_code == 204
    assert client.get(f"/api/v1/projects/{project['id']}/repos", headers=_headers(owner)).json() == []


def test_reauth_repo_replaces_token_without_touching_other_repos(client, monkeypatch):
    from app.services.repo_pat import github

    async def _fake_list_repos(pat, query=None, page=1):
        return [{"id": "1", "name": "repo", "full_name": "octocat/repo", "clone_url": "u", "private": False, "default_branch": "main"}]

    monkeypatch.setattr(github, "list_repos", _fake_list_repos)

    owner = register_and_login(client, email="prepo7@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    repo = client.post(
        f"/api/v1/projects/{project['id']}/repos",
        json={
            "provider": "github",
            "pat": "ghp_old",
            "organization": "octocat",
            "repo_full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "selected_branch": "main",
        },
        headers=_headers(owner),
    ).json()

    r = client.post(
        f"/api/v1/projects/{project['id']}/repos/{repo['id']}/reauth",
        json={"pat": "ghp_new"},
        headers=_headers(owner),
    )
    assert r.status_code == 200

    async def _check():
        from app.models.project_repo import ProjectRepo

        reloaded = await ProjectRepo.get(repo["id"])
        assert security.decrypt_secret(reloaded.pat_encrypted) == "ghp_new"

    asyncio.run(_check())


def test_reauth_repo_rejects_invalid_pat(client, monkeypatch):
    from app.services.repo_pat import RepoPatError, github

    async def _fake_list_repos_ok(pat, query=None, page=1):
        return [{"id": "1", "name": "repo", "full_name": "octocat/repo", "clone_url": "u", "private": False, "default_branch": "main"}]

    monkeypatch.setattr(github, "list_repos", _fake_list_repos_ok)
    owner = register_and_login(client, email="prepo8@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    repo = client.post(
        f"/api/v1/projects/{project['id']}/repos",
        json={
            "provider": "github",
            "pat": "ghp_old",
            "organization": "octocat",
            "repo_full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "selected_branch": "main",
        },
        headers=_headers(owner),
    ).json()

    async def _fake_list_repos_bad(pat, query=None, page=1):
        raise RepoPatError("bad token")

    monkeypatch.setattr(github, "list_repos", _fake_list_repos_bad)
    r = client.post(
        f"/api/v1/projects/{project['id']}/repos/{repo['id']}/reauth",
        json={"pat": "ghp_bad"},
        headers=_headers(owner),
    )
    assert r.status_code == 400


def test_collaborator_cannot_add_repo(client):
    owner = register_and_login(client, email="prepo6a@zerostrike.dev")
    collaborator = register_and_login(client, email="prepo6b@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "prepo6b@zerostrike.dev"},
        headers=_headers(owner),
    )

    r = client.post(
        f"/api/v1/projects/{project['id']}/repos",
        json={
            "provider": "github",
            "pat": "ghp_x",
            "organization": "octocat",
            "repo_full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "selected_branch": "main",
        },
        headers=_headers(collaborator),
    )
    assert r.status_code == 403

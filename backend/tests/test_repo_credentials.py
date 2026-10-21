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


def test_org_wide_azure_devops_credential_browses_project_then_repo_then_branch(client, monkeypatch):
    """Org + PAT is enough: the credential validates by listing projects, and the project is
    chosen per request — then carried onto the connected repo."""

    async def _fake_projects(pat, org):
        assert (pat, org) == ("ado-pat", "myorg")
        return [{"id": "p1", "name": "Alpha", "description": None}, {"id": "p2", "name": "Beta Team"}]

    async def _fake_ado_branches(pat, org, project, repo_id):
        assert (project, repo_id) == ("Beta Team", "guid-1")
        return [{"name": "main"}]

    monkeypatch.setattr(azure_devops, "list_projects", _fake_projects)
    monkeypatch.setattr(azure_devops, "list_repos", _fake_azure_list_repos)
    monkeypatch.setattr(azure_devops, "list_branches", _fake_ado_branches)
    owner = register_and_login(client, email="pat2@zerostrike.dev")
    h = _headers(owner)

    r = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "azure_devops", "pat": "ado-pat", "organization": "myorg"},
        headers=h,
    )
    assert r.status_code == 201
    cred = r.json()
    assert cred["ado_project"] is None

    projects = client.get(f"/api/v1/repo-credentials/{cred['id']}/projects", headers=h).json()
    assert [p["name"] for p in projects] == ["Alpha", "Beta Team"]

    # No project picked and none saved on the credential: a readable 400, not a call to ADO.
    assert client.get(f"/api/v1/repo-credentials/{cred['id']}/repos", headers=h).status_code == 400

    base = f"/api/v1/repo-credentials/{cred['id']}/repos"
    repos = client.get(base, params={"ado_project": "Beta Team"}, headers=h).json()
    assert repos[0]["full_name"] == "Beta Team/repo"
    branches = client.get(f"{base}/guid-1/branches", params={"ado_project": "Beta Team"}, headers=h).json()
    assert branches == [{"name": "main"}]

    project = client.post("/api/v1/projects", json={"name": "ado-proj"}, headers=h).json()
    connect = {
        "credential_id": cred["id"],
        "repo_full_name": repos[0]["full_name"],
        "clone_url": repos[0]["clone_url"],
        "selected_branch": "main",
    }
    r = client.post(f"/api/v1/projects/{project['id']}/repos", json=connect, headers=h)
    assert r.status_code == 400  # an org-wide credential must say which project
    r = client.post(
        f"/api/v1/projects/{project['id']}/repos", json={**connect, "ado_project": "Beta Team"}, headers=h
    )
    assert r.status_code == 201, r.text
    assert r.json()["ado_project"] == "Beta Team"


def test_projects_endpoint_is_azure_devops_only(client, monkeypatch):
    monkeypatch.setattr(github, "list_repos", _fake_github_list_repos)
    owner = register_and_login(client, email="pat2b@zerostrike.dev")
    cred = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "github", "pat": "ghp_secret", "organization": "octocat"},
        headers=_headers(owner),
    ).json()
    r = client.get(f"/api/v1/repo-credentials/{cred['id']}/projects", headers=_headers(owner))
    assert r.status_code == 400


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


# --- status / edit / reconnect (the Integrations page's row actions) --------------------------------


def _save_github_credential(client, monkeypatch, email, pat="ghp_old", label="Personal"):
    monkeypatch.setattr(github, "list_repos", _fake_github_list_repos)
    owner = register_and_login(client, email=email)
    r = client.post(
        "/api/v1/repo-credentials",
        json={"provider": "github", "pat": pat, "organization": "octocat", "label": label},
        headers=_headers(owner),
    )
    assert r.status_code == 201
    return owner, r.json()["id"]


def test_credential_status_reports_connected_then_invalid_when_the_token_stops_working(client, monkeypatch):
    owner, cid = _save_github_credential(client, monkeypatch, "st1@zerostrike.dev")

    ok = client.get(f"/api/v1/repo-credentials/{cid}/status", headers=_headers(owner)).json()
    assert ok["status"] == "connected" and ok["detail"] is None

    async def _revoked(pat, query=None, page=1):
        raise RepoPatError("Bad credentials")

    monkeypatch.setattr(github, "list_repos", _revoked)
    bad = client.get(f"/api/v1/repo-credentials/{cid}/status", headers=_headers(owner)).json()
    assert bad == {**bad, "status": "invalid", "detail": "Bad credentials"}


def test_credential_status_is_invalid_not_a_500_when_the_stored_token_cannot_be_decrypted(client, monkeypatch):
    from cryptography.fernet import InvalidToken

    owner, cid = _save_github_credential(client, monkeypatch, "st2@zerostrike.dev")

    def _unreadable(_credential):
        raise InvalidToken()

    from app.services import repo_credential_service

    monkeypatch.setattr(repo_credential_service, "decrypt_pat", _unreadable)
    r = client.get(f"/api/v1/repo-credentials/{cid}/status", headers=_headers(owner))
    assert r.status_code == 200 and r.json()["status"] == "invalid"


def test_editing_the_label_does_not_call_the_provider_and_can_clear_it(client, monkeypatch):
    owner, cid = _save_github_credential(client, monkeypatch, "ed1@zerostrike.dev")

    async def _must_not_run(*a, **k):
        raise AssertionError("a label edit must not hit the provider")

    monkeypatch.setattr(github, "list_repos", _must_not_run)
    r = client.patch(f"/api/v1/repo-credentials/{cid}", json={"label": "Work"}, headers=_headers(owner))
    assert r.status_code == 200 and r.json()["label"] == "Work"
    r = client.patch(f"/api/v1/repo-credentials/{cid}", json={"label": "  "}, headers=_headers(owner))
    assert r.json()["label"] is None and r.json()["organization"] == "octocat"


def test_changing_organization_revalidates_and_a_failure_changes_nothing(client, monkeypatch):
    owner, cid = _save_github_credential(client, monkeypatch, "ed2@zerostrike.dev")

    async def _nope(pat, org, project=None):
        raise RepoPatError("No access to that organization")

    monkeypatch.setattr(azure_devops, "list_projects", _nope)
    # GitHub credentials ignore org changes for validation but still accept the new name...
    r = client.patch(f"/api/v1/repo-credentials/{cid}", json={"organization": "other"}, headers=_headers(owner))
    assert r.status_code == 200 and r.json()["organization"] == "other"

    async def _fail(pat, query=None, page=1):
        raise RepoPatError("token lost access")

    monkeypatch.setattr(github, "list_repos", _fail)
    r = client.patch(f"/api/v1/repo-credentials/{cid}", json={"organization": "third"}, headers=_headers(owner))
    assert r.status_code == 400 and "lost access" in r.json()["detail"]
    listed = client.get("/api/v1/repo-credentials", headers=_headers(owner)).json()
    assert listed[0]["organization"] == "other"


def test_reconnect_replaces_the_token_only_when_the_new_one_validates(client, monkeypatch):
    owner, cid = _save_github_credential(client, monkeypatch, "rc1@zerostrike.dev", pat="ghp_old")

    async def _reject(pat, query=None, page=1):
        raise RepoPatError("Bad credentials")

    monkeypatch.setattr(github, "list_repos", _reject)
    r = client.put(f"/api/v1/repo-credentials/{cid}/token", json={"pat": "ghp_bad"}, headers=_headers(owner))
    assert r.status_code == 400

    monkeypatch.setattr(github, "list_repos", _fake_github_list_repos)
    r = client.put(f"/api/v1/repo-credentials/{cid}/token", json={"pat": "ghp_new"}, headers=_headers(owner))
    assert r.status_code == 200 and "pat" not in r.json() and "pat_encrypted" not in r.json()

    async def _check():
        from app.models.repo_credential import RepoCredential

        stored = await RepoCredential.get(cid)
        assert security.decrypt_secret(stored.pat_encrypted) == "ghp_new"

    import asyncio

    asyncio.run(_check())
    assert client.put(f"/api/v1/repo-credentials/{cid}/token", json={"pat": ""}, headers=_headers(owner)).status_code == 422


def test_status_edit_and_reconnect_404_for_someone_elses_credential(client, monkeypatch):
    _owner, cid = _save_github_credential(client, monkeypatch, "idor1@zerostrike.dev")
    intruder = register_and_login(client, email="idor2@zerostrike.dev")
    h = _headers(intruder)
    assert client.get(f"/api/v1/repo-credentials/{cid}/status", headers=h).status_code == 404
    assert client.patch(f"/api/v1/repo-credentials/{cid}", json={"label": "x"}, headers=h).status_code == 404
    assert client.put(f"/api/v1/repo-credentials/{cid}/token", json={"pat": "p"}, headers=h).status_code == 404

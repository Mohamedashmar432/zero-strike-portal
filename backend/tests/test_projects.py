from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name, "description": "d"}, headers=headers)
    assert r.status_code == 201
    return r.json()


def test_create_project_makes_creator_owner(client):
    tokens = register_and_login(client, email="owner@zerostrike.dev")
    project = _create_project(client, _headers(tokens))
    assert project["my_role"] == "owner"
    assert project["owner_id"]


def test_list_projects_scoped_to_membership(client):
    a = register_and_login(client, email="a@zerostrike.dev")
    b = register_and_login(client, email="b@zerostrike.dev")
    created = _create_project(client, _headers(a), name="A's project")

    body = client.get("/api/v1/projects", headers=_headers(a)).json()
    assert body["total"] == 1
    assert [p["id"] for p in body["items"]] == [created["id"]]
    assert body["items"][0]["name"] == "A's project"

    body = client.get("/api/v1/projects", headers=_headers(b)).json()
    assert body["total"] == 0
    assert body["items"] == []


def test_admin_sees_all_projects(client):
    owner = register_and_login(client, email="owner2@zerostrike.dev")
    created = _create_project(client, _headers(owner))
    admin_headers = _admin_headers(client, email="admin2@zerostrike.dev")

    body = client.get("/api/v1/projects", headers=admin_headers).json()
    assert body["total"] >= 1
    assert created["id"] in [p["id"] for p in body["items"]]


def test_non_member_forbidden_on_project_detail(client):
    owner = register_and_login(client, email="owner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    other = register_and_login(client, email="other3@zerostrike.dev")

    r = client.get(f"/api/v1/projects/{project['id']}", headers=_headers(other))
    assert r.status_code == 403


def test_get_unknown_project_is_404(client):
    tokens = register_and_login(client, email="lookup@zerostrike.dev")
    r = client.get("/api/v1/projects/000000000000000000000000", headers=_headers(tokens))
    assert r.status_code == 404


def test_collaborator_cannot_update_project(client):
    owner = register_and_login(client, email="owner4@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    collab = register_and_login(client, email="collab4@zerostrike.dev")
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "collab4@zerostrike.dev"},
        headers=_headers(owner),
    )

    r = client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": "renamed"}, headers=_headers(collab)
    )
    assert r.status_code == 403


def test_owner_can_update_project(client):
    owner = register_and_login(client, email="owner5@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    r = client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": "renamed"}, headers=_headers(owner)
    )
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"


def test_delete_project_cascades_and_is_audited(client):
    owner = register_and_login(client, email="owner6@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.post(
        "/api/v1/apikeys",
        json={"project_id": project["id"], "label": "k", "expires_in_days": 30},
        headers=_headers(owner),
    )

    r = client.delete(f"/api/v1/projects/{project['id']}", headers=_headers(owner))
    assert r.status_code == 204

    r = client.get(f"/api/v1/projects/{project['id']}", headers=_headers(owner))
    assert r.status_code == 404

    admin_headers = _admin_headers(client, email="admin6@zerostrike.dev")
    logs = client.get("/api/v1/audit-logs", headers=admin_headers).json()["items"]
    actions = [log["action"] for log in logs]
    assert "Project Created" in actions
    assert "Project Deleted" in actions

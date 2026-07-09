from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _create_scan(client, headers, project_id, **payload):
    r = client.post(f"/api/v1/projects/{project_id}/scans", json=payload, headers=headers)
    assert r.status_code == 201
    return r.json()


def test_create_local_scan_increments_project_scan_count(client):
    owner = register_and_login(client, email="sowner1@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan = _create_scan(client, _headers(owner), project["id"], scan_type="local")
    assert scan["scan_type"] == "local"
    assert scan["triggered_by"] == "manual"
    assert scan["status"] == "pending"

    detail = client.get(f"/api/v1/projects/{project['id']}", headers=_headers(owner)).json()
    assert detail["scan_count"] == 1
    assert detail["last_scan_at"] is not None


def test_create_cloud_scan_requires_repo_url(client):
    owner = register_and_login(client, email="sowner2@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    r = client.post(
        f"/api/v1/projects/{project['id']}/scans", json={"scan_type": "cloud"}, headers=_headers(owner)
    )
    assert r.status_code == 422

    scan = _create_scan(client, _headers(owner), project["id"], scan_type="cloud", repo_url="https://example.com/r.git")
    assert scan["repo_url"] == "https://example.com/r.git"


def test_create_cicd_scan_requires_ci_provider(client):
    owner = register_and_login(client, email="sowner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    r = client.post(
        f"/api/v1/projects/{project['id']}/scans", json={"scan_type": "cicd"}, headers=_headers(owner)
    )
    assert r.status_code == 422

    scan = _create_scan(client, _headers(owner), project["id"], scan_type="cicd", ci_provider="github_actions")
    assert scan["ci_provider"] == "github_actions"


def test_list_scans_scoped_to_project_and_paginated(client):
    owner = register_and_login(client, email="sowner4@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    other_project = _create_project(client, _headers(owner), name="Other")
    _create_scan(client, _headers(owner), project["id"], scan_type="local")
    _create_scan(client, _headers(owner), other_project["id"], scan_type="local")

    body = client.get(f"/api/v1/projects/{project['id']}/scans", headers=_headers(owner)).json()
    assert body["total"] == 1
    assert body["items"][0]["project_id"] == project["id"]


def test_get_scan_forbidden_for_non_member(client):
    owner = register_and_login(client, email="sowner5@zerostrike.dev")
    outsider = register_and_login(client, email="soutsider5@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan = _create_scan(client, _headers(owner), project["id"], scan_type="local")

    r = client.get(f"/api/v1/scans/{scan['id']}", headers=_headers(outsider))
    assert r.status_code == 403


def test_get_unknown_scan_is_404(client):
    owner = register_and_login(client, email="sowner6@zerostrike.dev")
    r = client.get("/api/v1/scans/000000000000000000000000", headers=_headers(owner))
    assert r.status_code == 404


def test_create_scan_rejected_on_archived_project(client):
    owner = register_and_login(client, email="sowner7@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.patch(f"/api/v1/projects/{project['id']}", json={"is_archived": True}, headers=_headers(owner))

    r = client.post(
        f"/api/v1/projects/{project['id']}/scans", json={"scan_type": "local"}, headers=_headers(owner)
    )
    assert r.status_code == 409


def test_mock_complete_transitions_status_and_sets_completed_at(client):
    owner = register_and_login(client, email="sowner8@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan = _create_scan(client, _headers(owner), project["id"], scan_type="local")

    r = client.post(f"/api/v1/scans/{scan['id']}/_mock-complete", json={}, headers=_headers(owner))
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["completed_at"] is not None


def test_mock_complete_failed_sets_error_message(client):
    owner = register_and_login(client, email="sowner9@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan = _create_scan(client, _headers(owner), project["id"], scan_type="local")

    r = client.post(
        f"/api/v1/scans/{scan['id']}/_mock-complete",
        json={"status": "failed", "error_message": "boom"},
        headers=_headers(owner),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["error_message"] == "boom"


def test_delete_project_cascades_scans(client):
    owner = register_and_login(client, email="sowner10@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan = _create_scan(client, _headers(owner), project["id"], scan_type="local")

    r = client.delete(f"/api/v1/projects/{project['id']}", headers=_headers(owner))
    assert r.status_code == 204

    r = client.get(f"/api/v1/scans/{scan['id']}", headers=_headers(owner))
    assert r.status_code == 404

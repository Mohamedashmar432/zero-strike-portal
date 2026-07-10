from pathlib import Path

from tests.test_auth_flow import register_and_login

_FIXTURE = Path(__file__).parent / "fixtures" / "go_report_sample.json"


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _project(client, headers, name="Demo"):
    return client.post("/api/v1/projects", json={"name": name}, headers=headers).json()


def _raw_key(client, headers, project_id):
    r = client.post(
        "/api/v1/apikeys",
        json={"project_id": project_id, "label": "scanner", "expires_in_days": 30},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()["raw_token"]


def _scanner(raw_token):
    return {"Authorization": f"Bearer {raw_token}"}


def _create_scan(client, raw_token, project_id):
    r = client.post(
        "/api/v1/scans",
        json={"project_id": project_id, "scanner_version": "v0.22.0", "branch": "main"},
        headers=_scanner(raw_token),
    )
    assert r.status_code == 201
    return r.json()


def test_create_scan_returns_pending_and_sets_scanner_fields(client):
    owner = register_and_login(client, email="scn1@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])

    body = _create_scan(client, token, project["id"])
    assert body["status"] == "pending"
    assert body["scan_id"]

    detail = client.get(f"/api/v1/scans/{body['scan_id']}", headers=_headers(owner)).json()
    assert detail["scan_type"] == "local"
    assert detail["triggered_by"] == "cli"
    assert detail["api_key_id"]
    assert detail["scanner_version"] == "v0.22.0"

    project_detail = client.get(f"/api/v1/projects/{project['id']}", headers=_headers(owner)).json()
    assert project_detail["scan_count"] == 1


def test_create_scan_project_mismatch_forbidden(client):
    owner = register_and_login(client, email="scn2@zerostrike.dev")
    project_a = _project(client, _headers(owner), name="A")
    project_b = _project(client, _headers(owner), name="B")
    token = _raw_key(client, _headers(owner), project_a["id"])

    r = client.post(
        "/api/v1/scans",
        json={"project_id": project_b["id"], "scanner_version": "v0.22.0"},
        headers=_scanner(token),
    )
    assert r.status_code == 403


def test_create_scan_on_archived_project_conflict(client):
    owner = register_and_login(client, email="scn3@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])
    client.patch(f"/api/v1/projects/{project['id']}", json={"is_archived": True}, headers=_headers(owner))

    r = client.post(
        "/api/v1/scans",
        json={"project_id": project["id"], "scanner_version": "v0.22.0"},
        headers=_scanner(token),
    )
    assert r.status_code == 409


def test_upload_json_ingests_and_completes(client):
    owner = register_and_login(client, email="scn4@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])
    scan = _create_scan(client, token, project["id"])

    raw = _FIXTURE.read_bytes()
    r = client.post(
        f"/api/v1/scans/{scan['scan_id']}/upload/json",
        content=raw,
        headers={**_scanner(token), "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "completed"
    assert body["findings"] == 4

    detail = client.get(f"/api/v1/scans/{scan['scan_id']}", headers=_headers(owner)).json()
    assert detail["status"] == "completed"
    assert detail["completed_at"] is not None

    # Re-upload replaces rather than duplicating.
    r = client.post(
        f"/api/v1/scans/{scan['scan_id']}/upload/json",
        content=raw,
        headers={**_scanner(token), "Content-Type": "application/json"},
    )
    assert r.status_code == 200
    assert r.json()["findings"] == 4


def test_upload_json_rejects_malformed_body(client):
    owner = register_and_login(client, email="scn5@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])
    scan = _create_scan(client, token, project["id"])

    r = client.post(
        f"/api/v1/scans/{scan['scan_id']}/upload/json",
        content=b'{"Findings": "not-a-list"}',
        headers={**_scanner(token), "Content-Type": "application/json"},
    )
    assert r.status_code == 422


def test_upload_html_stores_in_mongo(client):
    owner = register_and_login(client, email="scn6@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])
    scan = _create_scan(client, token, project["id"])
    client.post(
        f"/api/v1/scans/{scan['scan_id']}/upload/json",
        content=_FIXTURE.read_bytes(),
        headers={**_scanner(token), "Content-Type": "application/json"},
    )

    r = client.post(
        f"/api/v1/scans/{scan['scan_id']}/upload/html",
        files={"file": ("report.html", b"<html><body>report</body></html>", "text/html")},
        headers=_scanner(token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # HTML is persisted in Mongo (no filesystem) — surfaced as html_available on the report.
    report = client.get(f"/api/v1/scans/{scan['scan_id']}/report", headers=_headers(owner)).json()
    assert report["html_available"] is True


def test_status_update_marks_failed(client):
    owner = register_and_login(client, email="scn7@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])
    scan = _create_scan(client, token, project["id"])

    r = client.put(
        f"/api/v1/scans/{scan['scan_id']}/status",
        json={"status": "failed", "error_message": "pipeline blew up"},
        headers=_scanner(token),
    )
    assert r.status_code == 200

    detail = client.get(f"/api/v1/scans/{scan['scan_id']}", headers=_headers(owner)).json()
    assert detail["status"] == "failed"
    assert detail["error_message"] == "pipeline blew up"


def test_scan_from_another_project_key_is_404(client):
    owner = register_and_login(client, email="scn8@zerostrike.dev")
    project_a = _project(client, _headers(owner), name="A")
    project_b = _project(client, _headers(owner), name="B")
    token_a = _raw_key(client, _headers(owner), project_a["id"])
    token_b = _raw_key(client, _headers(owner), project_b["id"])
    scan_a = _create_scan(client, token_a, project_a["id"])

    # Key B must not touch project A's scan.
    r = client.put(
        f"/api/v1/scans/{scan_a['scan_id']}/status",
        json={"status": "failed"},
        headers=_scanner(token_b),
    )
    assert r.status_code == 404

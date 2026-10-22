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
    assert body["project_id"] == project["id"]
    assert body["project_name"] == project["name"]

    detail = client.get(f"/api/v1/scans/{body['scan_id']}", headers=_headers(owner)).json()
    assert detail["scan_type"] == "cicd"
    assert detail["triggered_by"] == "cli"
    assert detail["api_key_id"]
    assert detail["scanner_version"] == "v0.22.0"

    project_detail = client.get(f"/api/v1/projects/{project['id']}", headers=_headers(owner)).json()
    assert project_detail["scan_count"] == 1


def test_create_scan_without_project_id_in_body_succeeds(client):
    """New-style CLI: the token alone resolves the project, no --project-id needed."""
    owner = register_and_login(client, email="scn1b@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])

    r = client.post(
        "/api/v1/scans",
        json={"scanner_version": "v0.23.0", "branch": "main"},
        headers=_scanner(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["project_id"] == project["id"]
    assert body["project_name"] == project["name"]


def _stored_repo_url(client, owner, token, **fields):
    r = client.post("/api/v1/scans", json={"scanner_version": "v0.24.0", **fields}, headers=_scanner(token))
    assert r.status_code == 201
    detail = client.get(f"/api/v1/scans/{r.json()['scan_id']}", headers=_headers(owner)).json()
    return detail


def test_create_scan_stores_sanitized_repo_url(client):
    owner = register_and_login(client, email="scn1c@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])

    detail = _stored_repo_url(client, owner, token, repo_url="https://github.com/org/repo", branch="main")
    assert detail["repo_url"] == "https://github.com/org/repo"
    assert detail["branch"] == "main"

    # Credentials, query and fragment never reach the database.
    detail = _stored_repo_url(
        client, owner, token, repo_url="https://user:secret@github.com/org/repo.git?token=abc#frag"
    )
    assert detail["repo_url"] == "https://github.com/org/repo.git"
    detail = _stored_repo_url(client, owner, token, repo_url="https://ghp_tok@dev.azure.com/o/p/_git/r")
    assert detail["repo_url"] == "https://dev.azure.com/o/p/_git/r"


def test_create_scan_invalid_repo_url_is_stored_as_none(client):
    owner = register_and_login(client, email="scn1d@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])

    for bad in (
        "ssh://git@github.com/org/repo", "-oProxyCommand=x", "not a url", "", 42,
        "https://github.com/ghp_abcdefghijklmnopqrstuvwxyz0123456789/r", "https://github.com/o/r/extra",
    ):
        assert _stored_repo_url(client, owner, token, repo_url=bad)["repo_url"] is None


def test_create_scan_without_repo_url_or_branch_succeeds(client):
    """Older scanners send neither field."""
    owner = register_and_login(client, email="scn1e@zerostrike.dev")
    project = _project(client, _headers(owner))
    token = _raw_key(client, _headers(owner), project["id"])

    detail = _stored_repo_url(client, owner, token)
    assert detail["repo_url"] is None
    assert detail["branch"] is None


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


def test_health_reports_which_scanner_build_is_deployed(client, monkeypatch):
    """Which engine is deployed is the fact that made the large-repo failures diagnosable, and it
    was unanswerable from outside the container -- "scanner": true only ever meant the file
    exists, which a ten-releases-old build satisfies just as well as a current one."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "scanner_build_ref", "v0.34.0")
    body = client.get("/health").json()
    assert body["scanner_build"] == "v0.34.0"

    # An image built without the ref stamped must say so rather than render as blank: an ARG
    # default does not cross Docker build stages, so this is a realistic mis-build, not a
    # hypothetical one.
    monkeypatch.setattr(settings, "scanner_build_ref", "")
    assert client.get("/health").json()["scanner_build"] == "unknown"


# --- CI metadata on scan registration (classic Azure DevOps pipelines etc.) ---

_ADO_BODY = {
    "triggered_by": "ci",
    "ci_provider": "azure_pipelines",
    "ci_build_id": "4821",
    "ci_build_number": "20261022.3",
    "ci_build_url": "https://dev.azure.com/acme/proj/_build/results?buildId=4821&view=results",
}


def _setup(client, email):
    owner = register_and_login(client, email=email)
    project = _project(client, _headers(owner))
    return owner, project, _raw_key(client, _headers(owner), project["id"])


def _post_scan(client, token, body):
    return client.post("/api/v1/scans", json=body, headers=_scanner(token))


def test_legacy_body_defaults_to_cli_with_no_ci_metadata(client):
    owner, project, token = _setup(client, "ci-legacy@zerostrike.dev")
    sid = _create_scan(client, token, project["id"])["scan_id"]
    d = client.get(f"/api/v1/scans/{sid}", headers=_headers(owner)).json()
    assert (d["triggered_by"], d["scan_type"]) == ("cli", "cicd")
    assert d["ci_provider"] is d["ci_build_id"] is d["ci_build_number"] is d["ci_build_url"] is None


def test_full_ado_body_is_persisted_and_shown_in_detail(client):
    owner, project, token = _setup(client, "ci-ado@zerostrike.dev")
    r = _post_scan(client, token, {"project_id": project["id"], **_ADO_BODY})
    assert r.status_code == 201
    d = client.get(f"/api/v1/scans/{r.json()['scan_id']}", headers=_headers(owner)).json()
    assert (d["triggered_by"], d["scan_type"], d["ci_provider"]) == ("ci", "cicd", "azure_pipelines")
    assert d["ci_build_id"] == "4821"
    assert d["ci_build_number"] == "20261022.3"
    assert d["ci_build_url"] == _ADO_BODY["ci_build_url"]


def test_invalid_ci_metadata_is_422(client):
    _, project, token = _setup(client, "ci-422@zerostrike.dev")
    bad = [
        {"triggered_by": "cloud"},
        {"triggered_by": "manual"},
        {"triggered_by": "sync"},
        {"triggered_by": "bogus"},
        {**_ADO_BODY, "ci_provider": "azure_devops"},
        {**_ADO_BODY, "ci_provider": "jenkins"},
        {"ci_provider": "azure_pipelines"},
        {"triggered_by": "cli", "ci_build_id": "1"},
        {"triggered_by": "ci", "ci_build_id": "1"},
        {**_ADO_BODY, "ci_build_url": "javascript:alert(1)"},
        {**_ADO_BODY, "ci_build_url": "ftp://dev.azure.com/x"},
        {**_ADO_BODY, "ci_build_url": "https://u:p@dev.azure.com/x"},
        {**_ADO_BODY, "ci_build_url": "https://dev.azure.com/" + "a" * 2048},
        {**_ADO_BODY, "ci_build_id": "48 21"},
    ]
    for body in bad:
        r = _post_scan(client, token, body)
        assert r.status_code == 422, body


def test_blank_ci_values_become_none_and_are_accepted(client):
    owner, project, token = _setup(client, "ci-blank@zerostrike.dev")
    r = _post_scan(
        client,
        token,
        {"ci_provider": "", "ci_build_id": " ", "ci_build_number": "", "ci_build_url": ""},
    )
    assert r.status_code == 201
    d = client.get(f"/api/v1/scans/{r.json()['scan_id']}", headers=_headers(owner)).json()
    assert d["triggered_by"] == "cli"
    assert d["ci_provider"] is d["ci_build_id"] is d["ci_build_number"] is d["ci_build_url"] is None


def test_unknown_extra_field_is_ignored(client):
    _, project, token = _setup(client, "ci-extra@zerostrike.dev")
    r = _post_scan(client, token, {"some_future_field": "x", **_ADO_BODY})
    assert r.status_code == 201


def test_project_id_mismatch_is_still_403_with_ci_metadata(client):
    _, project, token = _setup(client, "ci-403@zerostrike.dev")
    r = _post_scan(client, token, {"project_id": "0" * 24, **_ADO_BODY})
    assert r.status_code == 403


def test_project_scan_list_includes_ci_fields(client):
    owner, project, token = _setup(client, "ci-list@zerostrike.dev")
    assert _post_scan(client, token, _ADO_BODY).status_code == 201
    items = client.get(f"/api/v1/projects/{project['id']}/scans", headers=_headers(owner)).json()["items"]
    assert items[0]["ci_provider"] == "azure_pipelines"
    assert items[0]["ci_build_number"] == "20261022.3"
    assert items[0]["ci_build_url"] == _ADO_BODY["ci_build_url"]

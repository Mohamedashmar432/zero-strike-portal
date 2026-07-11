from pathlib import Path

from tests.test_auth_flow import register_and_login

_FIXTURE = Path(__file__).parent / "fixtures" / "go_report_sample.json"
_EMPTY_REPORT = b'{"ScanID": "empty-1", "ScannerVersion": "v0.22.0", "Findings": [], "Stats": {}, "Diagnostics": []}'


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _create_scan(client, owner_headers, project_id, report_bytes=None):
    """Create a local scan via the api-key scanner endpoint, optionally uploading a report."""
    raw_token = client.post(
        "/api/v1/apikeys",
        json={"project_id": project_id, "label": "scanner", "expires_in_days": 30},
        headers=owner_headers,
    ).json()["raw_token"]
    sh = {"Authorization": f"Bearer {raw_token}"}
    scan_id = client.post(
        "/api/v1/scans", json={"project_id": project_id, "scanner_version": "v0.22.0"}, headers=sh
    ).json()["scan_id"]
    if report_bytes is not None:
        client.post(
            f"/api/v1/scans/{scan_id}/upload/json",
            content=report_bytes,
            headers={**sh, "Content-Type": "application/json"},
        )
    return scan_id


def test_scan_report_pdf_returns_pdf_for_completed_scan(client):
    owner = register_and_login(client, email="pdfowner1@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _create_scan(client, _headers(owner), project["id"], report_bytes=_FIXTURE.read_bytes())

    r = client.get(f"/api/v1/scans/{scan_id}/report/pdf", headers=_headers(owner))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert len(r.content) > 1000


def test_scan_report_pdf_handles_zero_findings(client):
    owner = register_and_login(client, email="pdfowner2@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _create_scan(client, _headers(owner), project["id"], report_bytes=_EMPTY_REPORT)

    r = client.get(f"/api/v1/scans/{scan_id}/report/pdf", headers=_headers(owner))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_scan_report_pdf_404_when_no_report_yet(client):
    owner = register_and_login(client, email="pdfowner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _create_scan(client, _headers(owner), project["id"])

    r = client.get(f"/api/v1/scans/{scan_id}/report/pdf", headers=_headers(owner))
    assert r.status_code == 404


def test_scan_report_pdf_forbidden_for_non_member(client):
    owner = register_and_login(client, email="pdfowner4@zerostrike.dev")
    outsider = register_and_login(client, email="pdfoutsider4@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _create_scan(client, _headers(owner), project["id"], report_bytes=_FIXTURE.read_bytes())

    r = client.get(f"/api/v1/scans/{scan_id}/report/pdf", headers=_headers(outsider))
    assert r.status_code == 403

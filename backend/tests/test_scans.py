import asyncio
from pathlib import Path

import app.services.scan_queue_service as scan_queue_service
from tests.test_auth_flow import register_and_login

_FIXTURE = Path(__file__).parent / "fixtures" / "go_report_sample.json"


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _scanner_scan(client, owner_headers, project_id, upload=False):
    """Create a local scan the real way — via the api-key scanner endpoint."""
    raw_token = client.post(
        "/api/v1/apikeys",
        json={"project_id": project_id, "label": "scanner", "expires_in_days": 30},
        headers=owner_headers,
    ).json()["raw_token"]
    sh = {"Authorization": f"Bearer {raw_token}"}
    scan_id = client.post(
        "/api/v1/scans", json={"project_id": project_id, "scanner_version": "v0.22.0"}, headers=sh
    ).json()["scan_id"]
    if upload:
        client.post(
            f"/api/v1/scans/{scan_id}/upload/json",
            content=_FIXTURE.read_bytes(),
            headers={**sh, "Content-Type": "application/json"},
        )
    return scan_id


async def _noop(*args, **kwargs):
    pass


# --- JWT create endpoint is cloud-only ---


def test_create_cloud_scan_schedules_execution(client, monkeypatch):
    monkeypatch.setattr(scan_queue_service, "drain_queue", _noop)
    owner = register_and_login(client, email="sowner1@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    r = client.post(
        f"/api/v1/projects/{project['id']}/scans",
        json={"scan_type": "cloud", "repo_url": "https://github.com/example/repo"},
        headers=_headers(owner),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["scan_type"] == "cloud"
    assert body["triggered_by"] == "cloud"
    assert body["status"] == "queued"

    detail = client.get(f"/api/v1/projects/{project['id']}", headers=_headers(owner)).json()
    assert detail["scan_count"] == 1


def test_create_local_via_jwt_is_rejected(client):
    owner = register_and_login(client, email="sowner2@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    r = client.post(
        f"/api/v1/projects/{project['id']}/scans", json={"scan_type": "local"}, headers=_headers(owner)
    )
    assert r.status_code == 400


def test_create_cicd_via_jwt_is_rejected(client):
    owner = register_and_login(client, email="sowner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    r = client.post(
        f"/api/v1/projects/{project['id']}/scans",
        json={"scan_type": "cicd", "ci_provider": "github_actions"},
        headers=_headers(owner),
    )
    assert r.status_code == 400


def test_create_cloud_scan_requires_repo_url(client):
    owner = register_and_login(client, email="sowner4@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    r = client.post(
        f"/api/v1/projects/{project['id']}/scans", json={"scan_type": "cloud"}, headers=_headers(owner)
    )
    assert r.status_code == 422


def _add_project_repo(client, headers, project_id, provider="github", branch="main"):
    payload = {
        "provider": provider,
        "pat": "pat-value",
        "organization": "org" if provider == "github" else "ado-org",
        "repo_full_name": "org/repo",
        "clone_url": "https://github.com/org/repo.git" if provider == "github" else "https://dev.azure.com/x",
        "selected_branch": branch,
    }
    if provider == "azure_devops":
        payload["ado_project"] = "ado-proj"
    r = client.post(f"/api/v1/projects/{project_id}/repos", json=payload, headers=headers)
    assert r.status_code == 201
    return r.json()


def test_create_cloud_scan_via_project_repo_id_resolves_url_branch_and_token(client, monkeypatch):
    monkeypatch.setattr(scan_queue_service, "drain_queue", _noop)
    owner = register_and_login(client, email="sowner-repoid1@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    project_repo = _add_project_repo(client, _headers(owner), project["id"], branch="release")

    r = client.post(
        f"/api/v1/projects/{project['id']}/scans",
        json={"scan_type": "cloud", "project_repo_id": project_repo["id"]},
        headers=_headers(owner),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["repo_url"] == project_repo["clone_url"]
    assert body["branch"] == "release"

    async def _check():
        from app.models.scan import Scan

        scan = await Scan.get(body["id"])
        assert scan.repo_token == "pat-value"
        assert scan.repo_token_auth_scheme == "basic"

    asyncio.run(_check())


def test_create_cloud_scan_via_project_repo_id_uses_basic_scheme_for_azure_devops(client, monkeypatch):
    monkeypatch.setattr(scan_queue_service, "drain_queue", _noop)
    owner = register_and_login(client, email="sowner-repoid2@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    project_repo = _add_project_repo(client, _headers(owner), project["id"], provider="azure_devops")

    r = client.post(
        f"/api/v1/projects/{project['id']}/scans",
        json={"scan_type": "cloud", "project_repo_id": project_repo["id"]},
        headers=_headers(owner),
    )
    assert r.status_code == 201

    async def _check():
        from app.models.scan import Scan

        scan = await Scan.get(r.json()["id"])
        assert scan.repo_token_auth_scheme == "basic"

    asyncio.run(_check())


def test_create_cloud_scan_with_project_repo_id_from_other_project_is_404(client, monkeypatch):
    monkeypatch.setattr(scan_queue_service, "drain_queue", _noop)
    owner = register_and_login(client, email="sowner-repoid3@zerostrike.dev")
    project_a = _create_project(client, _headers(owner), name="A")
    project_b = _create_project(client, _headers(owner), name="B")
    repo_on_a = _add_project_repo(client, _headers(owner), project_a["id"])

    r = client.post(
        f"/api/v1/projects/{project_b['id']}/scans",
        json={"scan_type": "cloud", "project_repo_id": repo_on_a["id"]},
        headers=_headers(owner),
    )
    assert r.status_code == 404


# --- listing / reading scans (rows created via the scanner endpoint) ---


def test_list_scans_scoped_to_project(client):
    owner = register_and_login(client, email="sowner5@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    other = _create_project(client, _headers(owner), name="Other")
    _scanner_scan(client, _headers(owner), project["id"])
    _scanner_scan(client, _headers(owner), other["id"])

    body = client.get(f"/api/v1/projects/{project['id']}/scans", headers=_headers(owner)).json()
    assert body["total"] == 1
    assert body["items"][0]["project_id"] == project["id"]


def test_scan_list_and_detail_carry_ai_analysis_status(client):
    from datetime import datetime, timezone

    from app.models.ai_analysis_job import AIAnalysisJob

    owner = register_and_login(client, email="saistatus@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _scanner_scan(client, _headers(owner), project["id"])

    async def _seed_running_ai_job():
        await AIAnalysisJob(
            kind="scan",
            project_id=project["id"],
            scan_id=scan_id,
            scope_key=scan_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        ).insert()

    asyncio.run(_seed_running_ai_job())

    detail = client.get(f"/api/v1/scans/{scan_id}", headers=_headers(owner)).json()
    assert detail["ai_analysis_status"] == "in_progress"
    assert detail["ai_analysis_started_at"] is not None
    # The tz-normalized timestamp must be an unambiguous UTC string (has offset/Z), not naive.
    assert detail["ai_analysis_started_at"].endswith(("Z", "+00:00"))

    listed = client.get(f"/api/v1/projects/{project['id']}/scans", headers=_headers(owner)).json()
    assert listed["items"][0]["ai_analysis_status"] == "in_progress"


def test_scan_without_ai_job_has_null_ai_status(client):
    owner = register_and_login(client, email="snoaistatus@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _scanner_scan(client, _headers(owner), project["id"])
    detail = client.get(f"/api/v1/scans/{scan_id}", headers=_headers(owner)).json()
    assert detail["ai_analysis_status"] is None
    assert detail["ai_analysis_started_at"] is None


def test_get_scan_forbidden_for_non_member(client):
    owner = register_and_login(client, email="sowner6@zerostrike.dev")
    outsider = register_and_login(client, email="soutsider6@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _scanner_scan(client, _headers(owner), project["id"])

    r = client.get(f"/api/v1/scans/{scan_id}", headers=_headers(outsider))
    assert r.status_code == 403


def test_get_unknown_scan_is_404(client):
    owner = register_and_login(client, email="sowner7@zerostrike.dev")
    r = client.get("/api/v1/scans/000000000000000000000000", headers=_headers(owner))
    assert r.status_code == 404


def test_scan_report_and_findings_readable(client):
    owner = register_and_login(client, email="sowner8@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _scanner_scan(client, _headers(owner), project["id"], upload=True)

    report = client.get(f"/api/v1/scans/{scan_id}/report", headers=_headers(owner)).json()
    assert report["duration_ms"] == 4200
    assert report["stats"]["by_kind"]["sast"] == 1

    findings = client.get(f"/api/v1/scans/{scan_id}/findings", headers=_headers(owner)).json()
    assert findings["total"] == 4

    critical = client.get(
        f"/api/v1/scans/{scan_id}/findings?severity=critical", headers=_headers(owner)
    ).json()
    assert critical["total"] == 1
    assert critical["items"][0]["rule_id"] == "ZS-PY-001"


def test_findings_expose_and_filter_by_priority(client):
    owner = register_and_login(client, email="sowner12@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _scanner_scan(client, _headers(owner), project["id"], upload=True)

    findings = client.get(f"/api/v1/scans/{scan_id}/findings", headers=_headers(owner)).json()
    by_rule = {f["rule_id"]: f for f in findings["items"]}
    assert by_rule["ZS-PY-001"]["priority_score"] == 10.0
    assert by_rule["ZS-PY-001"]["priority_tier"] == "critical"

    critical_priority = client.get(
        f"/api/v1/scans/{scan_id}/findings?priority=critical", headers=_headers(owner)
    ).json()
    assert critical_priority["total"] == 1
    assert critical_priority["items"][0]["rule_id"] == "ZS-PY-001"


def test_delete_project_cascades_scans_findings_reports(client):
    owner = register_and_login(client, email="sowner11@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _scanner_scan(client, _headers(owner), project["id"], upload=True)

    r = client.delete(f"/api/v1/projects/{project['id']}", headers=_headers(owner))
    assert r.status_code == 204
    assert client.get(f"/api/v1/scans/{scan_id}", headers=_headers(owner)).status_code == 404

    async def counts():
        from app.models.finding import Finding
        from app.models.report import Report

        return (
            await Finding.find(Finding.scan_id == scan_id).count(),
            await Report.find(Report.scan_id == scan_id).count(),
        )

    findings_left, reports_left = asyncio.run(counts())
    assert findings_left == 0
    assert reports_left == 0

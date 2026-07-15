import asyncio
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


def test_render_scan_report_html_standard_is_unaffected_by_the_new_param(client):
    async def run():
        from app.models.finding import Finding
        from app.models.report import Report
        from app.models.scan import Scan
        from app.services import pdf_report_service

        owner_tokens = register_and_login(client, email="pdfowner5@zerostrike.dev")
        project = _create_project(client, _headers(owner_tokens))
        scan_id = _create_scan(
            client, _headers(owner_tokens), project["id"], report_bytes=_FIXTURE.read_bytes()
        )
        scan = await Scan.get(scan_id)
        report = await Report.find_one(Report.scan_id == scan_id)
        findings = await Finding.find(Finding.scan_id == scan_id).to_list()

        html = pdf_report_service.render_scan_report_html(scan, report, findings, "standard")
        assert "ZeroStrike Scan Report" in html

    asyncio.run(run())


def test_render_scan_report_html_executive_includes_overall_risk_and_canonical_owasp_titles(client):
    async def run():
        from app.models.finding import Finding
        from app.models.report import Report
        from app.models.scan import Scan
        from app.services import pdf_report_service

        owner_tokens = register_and_login(client, email="pdfowner6@zerostrike.dev")
        project = _create_project(client, _headers(owner_tokens))
        scan_id = _create_scan(
            client, _headers(owner_tokens), project["id"], report_bytes=_FIXTURE.read_bytes()
        )
        scan = await Scan.get(scan_id)
        report = await Report.find_one(Report.scan_id == scan_id)
        findings = await Finding.find(Finding.scan_id == scan_id).to_list()

        html = pdf_report_service.render_scan_report_html(
            scan, report, findings, "executive", project_name="Demo"
        )
        assert "Overall Risk: CRITICAL" in html
        assert "Broken Access Control" in html
        assert "10.0/10" in html

    asyncio.run(run())


def test_scan_report_pdf_uses_executive_template_when_project_overrides(client):
    owner = register_and_login(client, email="pdfowner7@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.patch(
        f"/api/v1/projects/{project['id']}", json={"report_template": "executive"}, headers=_headers(owner)
    )
    scan_id = _create_scan(client, _headers(owner), project["id"], report_bytes=_FIXTURE.read_bytes())

    r = client.get(f"/api/v1/scans/{scan_id}/report/pdf", headers=_headers(owner))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"


def test_executive_template_remediation_plan_handles_findings_with_no_priority_score():
    # Findings ingested before priority_score/priority_tier existed have both fields as
    # None (see Finding model) — the remediation-plan section must not crash when
    # ranking a mix of scored and unscored findings.
    from datetime import datetime, timezone

    from app.models.finding import Finding, LocationEmbedded
    from app.models.report import Report, ScanStatsEmbedded
    from app.models.scan import Scan
    from app.services import pdf_report_service

    now = datetime.now(timezone.utc)
    scan = Scan(project_id="p1", scan_type="cloud", created_at=now, updated_at=now)
    report = Report(
        scan_id="s1",
        project_id="p1",
        stats=ScanStatsEmbedded(by_severity={"high": 1, "medium": 1}, by_kind={"sast": 2}),
        json_uploaded_at=now,
    )
    findings = [
        Finding(
            scan_id="s1",
            project_id="p1",
            rule_id="LEGACY-1",
            severity="high",
            message="Pre-existing finding from before priority scoring shipped",
            location=LocationEmbedded(file="a.py"),
            priority_score=None,
            priority_tier=None,
        ),
        Finding(
            scan_id="s1",
            project_id="p1",
            rule_id="NEW-1",
            severity="medium",
            message="Freshly ingested finding",
            location=LocationEmbedded(file="b.py"),
            priority_score=6.0,
            priority_tier="high",
        ),
    ]

    html = pdf_report_service.render_scan_report_html(scan, report, findings, "executive")
    assert "LEGACY-1" in html
    assert "NEW-1" in html

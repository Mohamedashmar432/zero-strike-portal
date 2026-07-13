import asyncio
from datetime import datetime, timezone

from app.models.finding import Finding, LocationEmbedded
from app.models.scan import Scan
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _seed_scan_and_findings(project_id: str, severities: list[str | None]) -> None:
    async def _seed():
        now = datetime.now(timezone.utc)
        scan = await Scan(
            project_id=project_id,
            scan_type="cicd",
            triggered_by="ci",
            status="completed",
            created_at=now,
            updated_at=now,
        ).insert()
        for severity in severities:
            await Finding(
                scan_id=str(scan.id),
                project_id=project_id,
                severity=severity,
                message="msg",
                location=LocationEmbedded(file="app.py"),
            ).insert()

    asyncio.run(_seed())


def test_dashboard_stats_scoped_to_membership(client):
    owner_a = register_and_login(client, email="dash-a@zerostrike.dev")
    project_a = _create_project(client, _headers(owner_a), name="A")
    _seed_scan_and_findings(project_a["id"], ["critical", "high", "medium", None])

    owner_b = register_and_login(client, email="dash-b@zerostrike.dev")
    project_b = _create_project(client, _headers(owner_b), name="B")
    _seed_scan_and_findings(project_b["id"], ["critical", "critical", "low"])

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner_a)).json()
    assert body["project_count"] == 1
    assert body["scan_count"] == 1
    assert body["findings_by_severity"] == {
        "critical": 1,
        "high": 1,
        "medium": 1,
        "low": 0,
        "info": 0,
    }


def test_dashboard_stats_admin_sees_global_totals(client):
    owner_a = register_and_login(client, email="dash-c@zerostrike.dev")
    project_a = _create_project(client, _headers(owner_a), name="C")
    _seed_scan_and_findings(project_a["id"], ["critical", "high"])

    owner_b = register_and_login(client, email="dash-d@zerostrike.dev")
    project_b = _create_project(client, _headers(owner_b), name="D")
    _seed_scan_and_findings(project_b["id"], ["critical", "low", "low"])

    admin_headers = _admin_headers(client, email="dash-admin@zerostrike.dev")
    body = client.get("/api/v1/dashboard/stats", headers=admin_headers).json()

    assert body["project_count"] >= 2
    assert body["scan_count"] >= 2
    assert body["findings_by_severity"]["critical"] >= 2
    assert body["findings_by_severity"]["high"] >= 1
    assert body["findings_by_severity"]["low"] >= 2


def test_dashboard_stats_zero_data_for_new_user(client):
    tokens = register_and_login(client, email="dash-empty@zerostrike.dev")
    body = client.get("/api/v1/dashboard/stats", headers=_headers(tokens)).json()

    assert body["project_count"] == 0
    assert body["scan_count"] == 0
    assert body["findings_by_severity"] == {
        "critical": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
        "info": 0,
    }

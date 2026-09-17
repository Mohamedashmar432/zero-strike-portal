import asyncio
from datetime import datetime, timedelta, timezone

from app.models.finding import Finding, LocationEmbedded
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _seed_scan_and_findings(project_id: str, severities: list[str | None], created_at: datetime | None = None) -> str:
    async def _seed():
        now = created_at or datetime.now(timezone.utc)
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
        return str(scan.id)

    return asyncio.run(_seed())


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
    assert body["recent_scans"] == []


def test_dashboard_recent_scans_scoped_and_per_scan_severity(client):
    owner_a = register_and_login(client, email="dash-recent-a@zerostrike.dev")
    project_a = _create_project(client, _headers(owner_a), name="Recent A")
    scan_id = _seed_scan_and_findings(project_a["id"], ["critical", "high", "high"])

    owner_b = register_and_login(client, email="dash-recent-b@zerostrike.dev")
    project_b = _create_project(client, _headers(owner_b), name="Recent B")
    _seed_scan_and_findings(project_b["id"], ["low"])

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner_a)).json()

    assert len(body["recent_scans"]) == 1
    item = body["recent_scans"][0]
    assert item["scan_id"] == scan_id
    assert item["project_id"] == project_a["id"]
    assert item["project_name"] == "Recent A"
    assert item["status"] == "completed"
    assert item["scan_type"] == "cicd"
    assert item["findings_by_severity"] == {"critical": 1, "high": 2, "medium": 0, "low": 0, "info": 0}


def test_dashboard_recent_scans_admin_sees_all_and_orders_newest_first(client):
    owner_a = register_and_login(client, email="dash-recent-c@zerostrike.dev")
    project_a = _create_project(client, _headers(owner_a), name="Recent C")
    older = datetime.now(timezone.utc) - timedelta(hours=1)
    older_scan_id = _seed_scan_and_findings(project_a["id"], ["low"], created_at=older)

    owner_b = register_and_login(client, email="dash-recent-d@zerostrike.dev")
    project_b = _create_project(client, _headers(owner_b), name="Recent D")
    newer_scan_id = _seed_scan_and_findings(project_b["id"], ["critical"])

    admin_headers = _admin_headers(client, email="dash-recent-admin@zerostrike.dev")
    body = client.get("/api/v1/dashboard/stats", headers=admin_headers).json()

    scan_ids = [s["scan_id"] for s in body["recent_scans"]]
    assert newer_scan_id in scan_ids
    assert older_scan_id in scan_ids
    assert scan_ids.index(newer_scan_id) < scan_ids.index(older_scan_id)


def test_dashboard_recent_scans_capped_at_five(client):
    owner = register_and_login(client, email="dash-recent-cap@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Recent Cap")
    for _ in range(7):
        _seed_scan_and_findings(project["id"], [])

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner)).json()
    assert len(body["recent_scans"]) == 5


# --- Current posture ---------------------------------------------------------------
# Findings are stored per scan and never superseded, so the dashboard used to group the whole
# findings collection and count a rescanned repo once per scan. These lock in the fix: exposure
# is the newest completed scan per repo scope, never the sum of every scan ever ingested.


def _seed_repo(project_id: str, label: str) -> str:
    async def _seed():
        now = datetime.now(timezone.utc)
        repo = await ProjectRepo(
            project_id=project_id,
            provider="github",
            organization="acme",
            repo_full_name=f"acme/{label}",
            clone_url=f"https://github.com/acme/{label}.git",
            selected_branch="main",
            created_by="seed",
            created_at=now,
            updated_at=now,
        ).insert()
        return str(repo.id)

    return asyncio.run(_seed())


def _seed_scan(
    project_id: str,
    severities: list[str | None],
    *,
    repo_id: str | None = None,
    status: str = "completed",
    created_at: datetime | None = None,
) -> str:
    async def _seed():
        now = created_at or datetime.now(timezone.utc)
        scan = await Scan(
            project_id=project_id,
            scan_type="cloud",
            triggered_by="cloud",
            status=status,
            project_repo_id=repo_id,
            created_at=now,
            updated_at=now,
        ).insert()
        for severity in severities:
            await Finding(
                scan_id=str(scan.id),
                project_id=project_id,
                project_repo_id=repo_id,
                severity=severity,
                message="msg",
                location=LocationEmbedded(file="app.py"),
            ).insert()
        return str(scan.id)

    return asyncio.run(_seed())


def test_posture_excludes_superseded_scans(client):
    """THE regression test: rescanning a repo must not double-count its findings."""
    owner = register_and_login(client, email="posture-superseded@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Superseded")
    repo = _seed_repo(project["id"], "repo-a")

    old = datetime.now(timezone.utc) - timedelta(days=2)
    _seed_scan(project["id"], ["critical", "critical", "high"], repo_id=repo, created_at=old)
    # Later scan of the SAME repo: two criticals were fixed, one high remains.
    _seed_scan(project["id"], ["high"], repo_id=repo)

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner)).json()
    sev = body["findings_by_severity"]
    assert (sev["critical"], sev["high"]) == (0, 1), "posture must reflect the latest scan, not the sum"
    assert body["scan_count"] == 2, "historical scan volume still counts both"
    assert body["posture_coverage"]["repos_scanned"] == 1


def test_posture_sums_one_latest_scan_per_repo(client):
    owner = register_and_login(client, email="posture-multi-repo@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="MultiRepo")
    repo_a = _seed_repo(project["id"], "repo-a")
    repo_b = _seed_repo(project["id"], "repo-b")

    old = datetime.now(timezone.utc) - timedelta(days=2)
    _seed_scan(project["id"], ["critical", "critical"], repo_id=repo_a, created_at=old)
    _seed_scan(project["id"], ["critical"], repo_id=repo_a)
    _seed_scan(project["id"], ["high"], repo_id=repo_b)

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner)).json()
    sev = body["findings_by_severity"]
    assert (sev["critical"], sev["high"]) == (1, 1)
    assert body["posture_coverage"]["repos_scanned"] == 2


def test_posture_keeps_the_unlinked_bucket(client):
    """A CI/hand-pasted scan belongs to no connected repo — it must not be silently dropped."""
    owner = register_and_login(client, email="posture-unlinked@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Unlinked")
    repo = _seed_repo(project["id"], "repo-a")
    _seed_scan(project["id"], ["critical"], repo_id=repo)
    _seed_scan(project["id"], ["low"], repo_id=None)

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner)).json()
    sev = body["findings_by_severity"]
    assert (sev["critical"], sev["low"]) == (1, 1)
    assert body["posture_coverage"]["has_unlinked_scans"] is True


def test_posture_ignores_incomplete_scans(client):
    owner = register_and_login(client, email="posture-incomplete@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Incomplete")
    repo = _seed_repo(project["id"], "repo-a")
    _seed_scan(project["id"], ["critical"], repo_id=repo)
    # A newer scan that never completed must not supersede the completed one, nor contribute.
    _seed_scan(project["id"], ["high", "high"], repo_id=repo, status="running")
    _seed_scan(project["id"], ["medium"], repo_id=repo, status="failed")

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner)).json()
    sev = body["findings_by_severity"]
    assert (sev["critical"], sev["high"], sev["medium"]) == (1, 0, 0)


def test_posture_reports_repos_with_no_completed_scan(client):
    owner = register_and_login(client, email="posture-uncovered@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Uncovered")
    repo_a = _seed_repo(project["id"], "repo-a")
    _seed_repo(project["id"], "repo-b")  # connected, never scanned
    _seed_scan(project["id"], ["high"], repo_id=repo_a)

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner)).json()
    coverage = body["posture_coverage"]
    assert coverage["repos_scanned"] == 1
    assert coverage["repos_without_completed_scan"] == 1


def test_posture_is_zero_without_completed_scans(client):
    """No completed scans must return zeros, never fall through to an unfiltered aggregate."""
    owner = register_and_login(client, email="posture-empty@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Empty")
    repo = _seed_repo(project["id"], "repo-a")
    _seed_scan(project["id"], ["critical", "high"], repo_id=repo, status="running")

    body = client.get("/api/v1/dashboard/stats", headers=_headers(owner)).json()
    assert body["findings_by_severity"] == {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}

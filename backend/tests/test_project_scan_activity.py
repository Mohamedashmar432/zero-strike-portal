import asyncio
from datetime import datetime, timedelta, timezone

from beanie import PydanticObjectId

from app.models.finding import Finding, LocationEmbedded
from app.models.project_repo import ProjectRepo
from app.models.scan import Scan
from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def _repo(project_id: str, full_name: str) -> ProjectRepo:
    now = datetime.now(timezone.utc)
    return await ProjectRepo(
        project_id=project_id,
        provider="github",
        organization="acme",
        repo_full_name=full_name,
        clone_url=f"https://github.com/{full_name}.git",
        selected_branch="main",
        pat_encrypted="x",
        created_by="u",
        created_at=now,
        updated_at=now,
    ).insert()


async def _scan_with_findings(project_id: str, repo_id: str | None, when: datetime, severities: list[str]) -> str:
    scan = await Scan(
        project_id=project_id,
        scan_type="cloud",
        status="completed",
        project_repo_id=repo_id,
        created_at=when,
        completed_at=when,
        updated_at=when,
    ).insert()
    for sev in severities:
        await Finding(
            scan_id=str(scan.id),
            project_id=project_id,
            project_repo_id=repo_id,
            severity=sev,
            message="m",
            location=LocationEmbedded(file="a.py"),
        ).insert()
    return str(scan.id)


def test_scan_activity_current_findings_is_latest_scan_per_repo(client):
    owner = register_and_login(client, email="activity@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    async def seed():
        r1 = await _repo(project["id"], "acme/one")
        r2 = await _repo(project["id"], "acme/two")
        # repo1: older scan has 5 findings, latest has just critical+high (2) -> only latest counts
        await _scan_with_findings(project["id"], str(r1.id), t0, ["low"] * 5)
        await _scan_with_findings(project["id"], str(r1.id), t0 + timedelta(days=1), ["critical", "high"])
        # repo2: single scan with 2 medium
        await _scan_with_findings(project["id"], str(r2.id), t0 + timedelta(hours=2), ["medium", "medium"])

    asyncio.run(seed())

    r = client.get(f"/api/v1/projects/{project['id']}/scan-activity", headers=_headers(owner))
    assert r.status_code == 200
    body = r.json()

    # current = latest-per-repo summed: repo1 (crit1+high1) + repo2 (med2) = 4, NOT the 9 all-time.
    assert body["current_findings_total"] == 4
    assert body["current_findings"]["critical"] == 1
    assert body["current_findings"]["high"] == 1
    assert body["current_findings"]["medium"] == 2

    groups = {g["repo_label"]: g for g in body["repos"]}
    assert groups["acme/one"]["scans"][0]["total_findings"] == 2  # newest first
    assert groups["acme/one"]["scans"][1]["total_findings"] == 5
    assert groups["acme/two"]["scans"][0]["total_findings"] == 2


def test_scan_activity_includes_unlinked_scans(client):
    owner = register_and_login(client, email="unlinked@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    t0 = datetime(2026, 2, 1, tzinfo=timezone.utc)

    async def seed():
        await _scan_with_findings(project["id"], None, t0, ["high"])  # no connected repo

    asyncio.run(seed())

    body = client.get(f"/api/v1/projects/{project['id']}/scan-activity", headers=_headers(owner)).json()
    labels = [g["repo_label"] for g in body["repos"]]
    assert "Unlinked scans" in labels
    assert body["current_findings_total"] == 1


def test_project_ai_usage_aggregates_and_is_project_scoped(client):
    from app.services import ai_provider_config_service as svc

    owner = register_and_login(client, email="aiusage@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    async def seed():
        cfg_id = str(PydanticObjectId())
        await svc.record_usage(
            cfg_id, success=True, prompt_tokens=100, completion_tokens=40, cost_usd=0.01,
            provider="openai", model_name="gpt", project_id=project["id"],
        )
        await svc.record_usage(
            cfg_id, success=True, prompt_tokens=50, completion_tokens=10, cost_usd=0.005,
            provider="openai", model_name="gpt", project_id=project["id"],
        )
        # another project's usage must not bleed in
        await svc.record_usage(
            cfg_id, success=True, prompt_tokens=999, completion_tokens=999, cost_usd=1.0,
            provider="openai", model_name="gpt", project_id="someone-else",
        )
        # a failed call records no event
        await svc.record_usage(cfg_id, success=False, provider="openai", project_id=project["id"])

    asyncio.run(seed())

    body = client.get(f"/api/v1/projects/{project['id']}/ai-usage", headers=_headers(owner)).json()
    assert body["total_requests"] == 2
    assert body["total_prompt_tokens"] == 150
    assert body["total_completion_tokens"] == 50

"""Suppressed findings: stored, never counted. False-positive verdicts and retired rules."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.models.finding import Finding
from app.models.project import Project
from app.models.report import Report
from app.models.scan import Scan
from app.models.scan_engine import RulePackVersion
from app.models.vulnerability import Vulnerability
from app.schemas.report import GoReportIn
from app.services import report_ingestion_service as ingest_svc
from tests.test_auth_flow import register_and_login

_FIXTURE = Path(__file__).parent / "fixtures" / "go_report_sample.json"
_SQLI_FP = "fp-sqli-001"


def _report() -> GoReportIn:
    return GoReportIn.model_validate(json.loads(_FIXTURE.read_text()))


async def _project(name="P") -> Project:
    now = datetime.now(timezone.utc)
    p = Project(name=name, owner_id="o1", created_at=now, updated_at=now)
    await p.insert()
    return p


async def _ingest(project_id: str, report: GoReportIn | None = None) -> Scan:
    now = datetime.now(timezone.utc)
    scan = Scan(project_id=project_id, scan_type="cicd", created_at=now, updated_at=now)
    await scan.insert()
    await ingest_svc.ingest(scan, report or _report(), raw_json=_FIXTURE.read_text())
    return scan


async def _tag_false_positive(project_id: str, fingerprint: str) -> None:
    v = await Vulnerability.find_one(
        Vulnerability.project_id == project_id, Vulnerability.fingerprint == fingerprint
    )
    v.status, v.resolution_reason, v.resolution_comment = "resolved", "false_positive", "test-only helper"
    await v.save()


async def _suppressed(scan: Scan) -> dict[str, str | None]:
    rows = await Finding.find(Finding.scan_id == str(scan.id)).to_list()
    return {f.fingerprint: f.suppressed_reason for f in rows if f.suppressed}


def test_false_positive_verdict_suppresses_on_the_next_scan(client):
    async def run():
        p = await _project()
        pid = str(p.id)
        await _ingest(pid)
        await _tag_false_positive(pid, _SQLI_FP)
        scan2 = await _ingest(pid)

        assert await _suppressed(scan2) == {_SQLI_FP: "false_positive"}
        assert scan2.suppressed_count == 1
        # stored, so the scan page can still show it
        assert await Finding.find(Finding.scan_id == str(scan2.id)).count() == 4
        # ...but not counted: report stats and the project rollup both leave it out
        report = await Report.find_one(Report.scan_id == str(scan2.id))
        assert report.stats.total_findings == 3
        assert "critical" not in report.stats.by_severity
        assert report.stats.suppressed == 1 + 1  # the scanner's own allow-file count + ours
        project = await Project.get(pid)
        assert project.finding_severity_counts.get("critical", 0) == 1  # scan 1 only
        assert project.total_findings == 4 + 3

    asyncio.run(run())


def test_same_rule_on_a_new_fingerprint_is_still_reported(client):
    async def run():
        p = await _project()
        pid = str(p.id)
        await _ingest(pid)
        await _tag_false_positive(pid, _SQLI_FP)
        changed = json.loads(_FIXTURE.read_text())
        changed["Findings"][0]["Fingerprint"] = "fp-sqli-NEW"
        scan2 = await _ingest(pid, GoReportIn.model_validate(changed))
        assert await _suppressed(scan2) == {}

    asyncio.run(run())


def test_another_projects_verdict_does_not_suppress(client):
    async def run():
        a, b = await _project("A"), await _project("B")
        await _ingest(str(a.id))
        await _tag_false_positive(str(a.id), _SQLI_FP)
        scan_b = await _ingest(str(b.id))
        assert await _suppressed(scan_b) == {}

    asyncio.run(run())


def test_retired_rule_is_suppressed_and_scan_records_pack_version(client):
    async def run():
        await RulePackVersion(
            version=3, retired_rule_ids=["ZS-SEC-003"], changelog="x", published_by="admin"
        ).insert()
        p = await _project()
        scan = await _ingest(str(p.id))
        assert await _suppressed(scan) == {"fp-secret-002": "rule_retired"}
        assert scan.rule_pack_version == 3
        report = await Report.find_one(Report.scan_id == str(scan.id))
        assert report.stats.by_severity.get("high") is None

    asyncio.run(run())


def _auth(client, email):
    return {"Authorization": f"Bearer {register_and_login(client, email=email)['access_token']}"}


def test_scan_findings_api_hides_suppressed_unless_asked(client):
    headers = _auth(client, "fp@zerostrike.dev")
    pid = client.post("/api/v1/projects", json={"name": "FP API"}, headers=headers).json()["id"]

    async def run() -> str:
        await _ingest(pid)
        await _tag_false_positive(pid, _SQLI_FP)
        return str((await _ingest(pid)).id)

    scan_id = asyncio.run(run())
    shown = client.get(f"/api/v1/scans/{scan_id}/findings", headers=headers).json()
    assert shown["total"] == 3
    assert _SQLI_FP not in {f["fingerprint"] for f in shown["items"]}
    only = client.get(f"/api/v1/scans/{scan_id}/findings?suppressed=true", headers=headers).json()
    assert [f["fingerprint"] for f in only["items"]] == [_SQLI_FP]
    assert only["items"][0]["suppressed_reason"] == "false_positive"
    scan = client.get(f"/api/v1/scans/{scan_id}", headers=headers).json()
    assert scan["suppressed_count"] == 1


def test_false_positive_resolution_requires_a_comment(client):
    headers = _auth(client, "fp2@zerostrike.dev")
    pid = client.post("/api/v1/projects", json={"name": "FP comment"}, headers=headers).json()["id"]

    async def run() -> str:
        await _ingest(pid)
        v = await Vulnerability.find_one(Vulnerability.project_id == pid, Vulnerability.fingerprint == _SQLI_FP)
        return str(v.id)

    vid = asyncio.run(run())
    url = f"/api/v1/projects/{pid}/vulnerabilities/{vid}/status"
    body = {"status": "resolved", "resolution_reason": "false_positive"}
    assert client.patch(url, json=body, headers=headers).status_code == 422
    assert client.patch(url, json=body | {"resolution_comment": "   "}, headers=headers).status_code == 422
    ok = client.patch(url, json=body | {"resolution_comment": "test fixture, not reachable"}, headers=headers)
    assert ok.status_code == 200


def test_suppressed_findings_are_left_out_of_every_aggregate(client):
    from app.services import project_stats_service as stats_svc

    async def run():
        p = await _project()
        pid = str(p.id)
        await _ingest(pid)
        await _tag_false_positive(pid, _SQLI_FP)
        scan2 = await _ingest(pid)
        sid = str(scan2.id)

        per_scan = (await stats_svc.get_severity_by_scan_ids([sid]))[sid]
        assert per_scan.critical == 0 and per_scan.high == 1
        # the per-scan severity group is a Mongo-side $match, so a rollup recompute agrees
        assert await stats_svc.reconcile_project_finding_counts() >= 0
        project = await Project.get(pid)
        assert project.total_findings == 4 + 3
        assert (await Finding.find(Finding.scan_id == sid, {"suppressed": True}).count()) == 1

    asyncio.run(run())

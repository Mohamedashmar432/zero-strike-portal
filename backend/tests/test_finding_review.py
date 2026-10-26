"""Admin-reviewed CI exemptions (docs/FINDING_REVIEW.md): a member asks, a portal admin decides, and
only an accepted review stops a finding counting -- in the portal and in the scanner's CI gate."""

import asyncio
import json
from datetime import datetime, timezone

from app.models.audit_log import AuditLog
from app.models.finding import Finding
from app.models.scan import Scan
from app.models.vulnerability import Vulnerability
from app.schemas.report import GoReportIn
from app.services import finding_review_service
from app.services import report_ingestion_service as ingest_svc
from tests.test_auth_flow import register_and_login
from tests.test_scanner_endpoints import _raw_key, _scanner
from tests.test_users import _promote_to_admin
from tests.test_vulnerabilities_api import VULN_URL, _create_project, _headers, _seed_and_reconcile, _vuln_id

REVIEWS = "/api/v1/admin/finding-reviews"


def _setup(client, tag):
    member = register_and_login(client, email=f"member-{tag}@zs.dev")
    project = _create_project(client, _headers(member), name=f"Review {tag}")
    register_and_login(client, email=f"admin-{tag}@zs.dev")
    _promote_to_admin(f"admin-{tag}@zs.dev")
    admin = client.post("/api/v1/auth/login", json={"email": f"admin-{tag}@zs.dev", "password": "hunter2pass"}).json()
    _seed_and_reconcile(
        project["id"],
        [
            {"fingerprint": "fp-sqli", "severity": "critical", "file": "src/db.py"},
            {"fingerprint": "fp-dep", "severity": "high", "kind": "sca", "file": "requirements.txt",
             "rule_id": "ZS-SCA-001", "rule_name": "Vulnerable Dependency"},
        ],
    )
    return _headers(member), _headers(admin), project["id"]


def _request(client, headers, pid, fingerprint, **body):
    url = f"{VULN_URL.format(project_id=pid)}/{_vuln_id(pid, fingerprint)}/status"
    return client.patch(url, json=body, headers=headers)


def _exemptions(client, headers, pid):
    token = _raw_key(client, headers, pid)
    r = client.post("/api/v1/scans", json={}, headers=_scanner(token))
    assert r.status_code == 201
    return r.json()["accepted_exemptions"]


def _ingest(pid, findings, exempted=()):
    """A CI upload: `findings` counted by the scanner, `exempted` moved to AcceptedExemptions."""

    def go(fp, file, sev="critical"):
        return {"ID": fp, "RuleID": "rule-a", "RuleName": "SQL Injection", "Severity": sev, "Fingerprint": fp,
                "Kind": "sast", "Message": "m", "Location": {"File": file, "StartLine": 3}}

    report = GoReportIn.model_validate({
        "RootPath": ".",
        "Findings": [go(*f) for f in findings],
        "AcceptedExemptions": [{"Fingerprint": fp, "File": file, "Kind": "false_positive", "Finding": go(fp, file)}
                               for fp, file in exempted],
    })

    async def run():
        now = datetime.now(timezone.utc)
        scan = Scan(project_id=pid, scan_type="cicd", created_at=now, updated_at=now)
        await scan.insert()
        await ingest_svc.ingest(scan, report, raw_json=json.dumps({}))
        rows = await Finding.find(Finding.scan_id == str(scan.id)).to_list()
        return {(f.fingerprint, f.location.file): f.suppressed_reason for f in rows}

    return asyncio.run(run())


def test_member_request_keeps_blocking_until_an_admin_accepts(client):
    member, admin, pid = _setup(client, "a")

    r = _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive",
                 resolution_comment="query is a constant")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "open"  # still blocking
    assert body["review"]["status"] == "pending" and body["review"]["file_path"] == "src/db.py"
    assert body["review"]["requested_by_email"] == "member-a@zs.dev"
    assert _exemptions(client, member, pid) == []

    queue = client.get(REVIEWS, headers=admin).json()
    assert queue["pending_count"] >= 1
    item = next(i for i in queue["items"] if i["vulnerability_id"] == _vuln_id(pid, "fp-sqli"))
    assert item["project_name"] == "Review a" and item["requested_by_email"] == "member-a@zs.dev"

    # A member can neither see the queue nor decide.
    assert client.get(REVIEWS, headers=member).status_code == 403
    vid = _vuln_id(pid, "fp-sqli")
    assert client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "accept"}, headers=member).status_code == 403

    r = client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "accept", "comment": "agreed"}, headers=admin)
    assert r.status_code == 200 and r.json()["review"]["status"] == "accepted"
    v = client.get(f"{VULN_URL.format(project_id=pid)}/{vid}", headers=member).json()
    assert v["status"] == "resolved" and v["resolution_reason"] == "false_positive"
    assert _exemptions(client, member, pid) == [{"fingerprint": "fp-sqli", "file": "src/db.py", "kind": "false_positive"}]

    # Deciding twice is refused.
    assert client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "reject", "comment": "x"}, headers=admin).status_code == 409


def test_exemption_matches_fingerprint_and_file_only(client):
    member, admin, pid = _setup(client, "b")
    _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive", resolution_comment="c")
    vid = _vuln_id(pid, "fp-sqli")
    client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "accept"}, headers=admin)

    seen = _ingest(pid, [("fp-sqli", "src/db.py"), ("fp-sqli", "src/other.py")])
    assert seen[("fp-sqli", "src/db.py")] == "false_positive"
    assert seen[("fp-sqli", "src/other.py")] is None  # same snippet, another file: still counted

    # What the scanner moved aside is stored, suppressed -- the scan record stays complete.
    seen = _ingest(pid, [], exempted=[("fp-sqli", "src/db.py")])
    assert seen == {("fp-sqli", "src/db.py"): "false_positive"}


def test_dependency_findings_get_accepted_risk_never_false_positive(client):
    member, admin, pid = _setup(client, "c")
    r = _request(client, member, pid, "fp-dep", status="resolved", resolution_reason="false_positive", resolution_comment="c")
    assert r.status_code == 422 and "accepted risk" in r.json()["detail"]

    r = _request(client, member, pid, "fp-dep", status="accepted_risk", resolution_comment="not reachable from our code")
    assert r.status_code == 200 and r.json()["review"]["kind"] == "accepted_risk"
    assert r.json()["status"] == "open"

    vid = _vuln_id(pid, "fp-dep")
    client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "accept"}, headers=admin)
    v = client.get(f"{VULN_URL.format(project_id=pid)}/{vid}", headers=member).json()
    assert v["status"] == "accepted_risk"
    assert {"fingerprint": "fp-dep", "file": "requirements.txt", "kind": "accepted_risk"} in _exemptions(client, member, pid)


def test_comment_is_required_and_reject_keeps_blocking(client):
    member, admin, pid = _setup(client, "d")
    assert _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive",
                    resolution_comment="  ").status_code == 422
    _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive", resolution_comment="c")
    vid = _vuln_id(pid, "fp-sqli")
    assert client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "reject"}, headers=admin).status_code == 422
    r = client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "reject", "comment": "it is user input"}, headers=admin)
    assert r.status_code == 200 and r.json()["review"]["status"] == "rejected"
    assert r.json()["vulnerability_status"] == "open"
    assert _exemptions(client, member, pid) == []


def test_revoke_puts_the_finding_back_in_the_gate(client):
    member, admin, pid = _setup(client, "e")
    _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive", resolution_comment="c")
    vid = _vuln_id(pid, "fp-sqli")
    assert client.post(f"{REVIEWS}/{vid}/revoke", json={"comment": "x"}, headers=admin).status_code == 409  # not accepted yet
    client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "accept"}, headers=admin)
    r = client.post(f"{REVIEWS}/{vid}/revoke", json={"comment": "code changed meaning"}, headers=admin)
    assert r.status_code == 200 and r.json()["review"]["status"] == "revoked"
    assert r.json()["vulnerability_status"] == "open"
    assert _exemptions(client, member, pid) == []
    assert _ingest(pid, [("fp-sqli", "src/db.py")])[("fp-sqli", "src/db.py")] is None
    # The requester hears about it: the exemption they were relying on is gone.
    titles = [n["title"] for n in client.get("/api/v1/notifications?limit=20", headers=member).json()["items"]]
    assert "Your false positive exemption was revoked" in titles


def test_exemptions_never_cross_projects(client):
    member, admin, pid = _setup(client, "f")
    _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive", resolution_comment="c")
    client.post(f"{REVIEWS}/{_vuln_id(pid, 'fp-sqli')}/decide", json={"decision": "accept"}, headers=admin)
    other = _create_project(client, member, name="Other f")
    assert _exemptions(client, member, other["id"]) == []


def test_self_approval_is_allowed_and_recorded(client):
    _member, admin, pid = _setup(client, "g")
    # The admin is not a project member but, as portal admin, may request and approve.
    _request(client, admin, pid, "fp-sqli", status="resolved", resolution_reason="false_positive", resolution_comment="c")
    vid = _vuln_id(pid, "fp-sqli")
    assert client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "accept"}, headers=admin).status_code == 200

    async def audit():
        return await AuditLog.find_one(AuditLog.action == "Finding Review Accepted", AuditLog.target_id == vid)

    assert asyncio.run(audit()).metadata["self_approved"] is True


def test_unreviewed_false_positives_migrate_to_pending_and_dependencies_reopen(client):
    member, _admin, pid = _setup(client, "h")

    async def legacy():
        now = datetime.now(timezone.utc)
        for fp in ("fp-sqli", "fp-dep"):
            v = await Vulnerability.find_one(Vulnerability.project_id == pid, Vulnerability.fingerprint == fp)
            v.status, v.resolution_reason, v.resolution_comment = "resolved", "false_positive", "old verdict"
            v.resolved_by_user_id, v.resolved_at = "u-legacy", now
            await v.save()
        first = await finding_review_service.migrate_unreviewed_false_positives()
        second = await finding_review_service.migrate_unreviewed_false_positives()
        code = await Vulnerability.find_one(Vulnerability.project_id == pid, Vulnerability.fingerprint == "fp-sqli")
        dep = await Vulnerability.find_one(Vulnerability.project_id == pid, Vulnerability.fingerprint == "fp-dep")
        return first, second, code, dep

    first, second, code, dep = asyncio.run(legacy())
    assert (first, second) == (2, 0)  # idempotent
    assert code.status == "open" and code.review.status == "pending"
    assert code.review.request_comment == "old verdict" and code.review.requested_by_user_id == "u-legacy"
    assert dep.status == "open" and dep.review is None
    assert _exemptions(client, member, pid) == []

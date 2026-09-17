"""API integration tests for the vulnerability lifecycle: the work-queue list/detail, the
status/assignment transitions a human owns, the per-scan regression read, and the
project-scoped audit log added alongside it. Findings are seeded directly and run through the
real `vulnerability_service.reconcile_scan` (Stage 1, unmodified) rather than re-implementing
its reconciliation rules here -- see test_compliance_api.py for the same
seed-directly-bypass-the-scanner convention.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.models.finding import Finding, LocationEmbedded
from app.models.finding_comment import FindingComment
from app.models.scan import Scan
from app.models.vulnerability import Vulnerability
from app.services import vulnerability_service
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

VULN_URL = "/api/v1/projects/{project_id}/vulnerabilities"


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Vuln Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _invite(client, headers, project_id, email, role="collaborator"):
    r = client.post(
        f"/api/v1/projects/{project_id}/members", json={"email": email, "role": role}, headers=headers
    )
    assert r.status_code == 201


def _seed_and_reconcile(project_id, specs, *, status="completed", created_at=None):
    """Insert a Scan + its Findings directly, then run the real reconcile_scan over them --
    exactly what report_ingestion_service.ingest() does after a real scan. Returns
    (scan_id, {fingerprint: Finding})."""

    async def _do():
        now = created_at or datetime.now(timezone.utc)
        scan = Scan(project_id=project_id, scan_type="cloud", status=status, created_at=now, updated_at=now)
        await scan.insert()
        findings = []
        for spec in specs:
            f = Finding(
                scan_id=str(scan.id),
                project_id=project_id,
                fingerprint=spec["fingerprint"],
                rule_id=spec.get("rule_id", "rule-a"),
                rule_name=spec.get("rule_name", "SQL Injection"),
                message=spec.get("message", "A finding"),
                location=LocationEmbedded(file=spec.get("file", "app.py"), start_line=3),
                severity=spec.get("severity", "high"),
                kind=spec.get("kind", "sast"),
                created_at=now,
            )
            await f.insert()
            findings.append(f)
        await vulnerability_service.reconcile_scan(scan, findings)
        # Re-fetch: reconcile_scan stamps vulnerability_id onto the Finding docs after insert.
        findings = await Finding.find(Finding.scan_id == str(scan.id)).to_list()
        return str(scan.id), {f.fingerprint: f for f in findings}

    return asyncio.run(_do())


def _vuln_id(project_id, fingerprint):
    async def _do():
        v = await Vulnerability.find_one(
            Vulnerability.project_id == project_id, Vulnerability.fingerprint == fingerprint
        )
        return str(v.id)

    return asyncio.run(_do())


# --- list ------------------------------------------------------------------------------


def test_list_filters_status_severity_assignee_and_regression_state(client):
    owner = register_and_login(client, email="vuln-list@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_and_reconcile(
        project["id"],
        [
            {"fingerprint": "fp-crit", "severity": "critical", "rule_name": "SQL Injection"},
            {"fingerprint": "fp-med", "severity": "medium", "rule_name": "Weak Hash"},
        ],
    )

    body = client.get(VULN_URL.format(project_id=project["id"]), headers=headers).json()
    assert body["total"] == 2

    r = client.get(f"{VULN_URL.format(project_id=project['id'])}?severity=critical", headers=headers)
    assert [i["fingerprint"] for i in r.json()["items"]] == ["fp-crit"]

    r = client.get(f"{VULN_URL.format(project_id=project['id'])}?status=open", headers=headers)
    assert r.json()["total"] == 2

    vid = _vuln_id(project["id"], "fp-crit")
    url = f"{VULN_URL.format(project_id=project['id'])}/{vid}/status"
    r = client.patch(
        url, json={"status": "resolved", "resolution_reason": "false_positive"}, headers=headers
    )
    assert r.status_code == 200

    r = client.get(f"{VULN_URL.format(project_id=project['id'])}?status=resolved", headers=headers)
    assert [i["fingerprint"] for i in r.json()["items"]] == ["fp-crit"]

    r = client.get(
        f"{VULN_URL.format(project_id=project['id'])}?regression_state=new", headers=headers
    )
    assert r.json()["total"] == 2  # both were reconciled as "new" and the status patch doesn't touch it


def test_list_search_matches_rule_name_message_and_fingerprint(client):
    owner = register_and_login(client, email="vuln-search@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_and_reconcile(
        project["id"],
        [
            {"fingerprint": "fp-needle-xyz", "rule_name": "Hardcoded Secret", "message": "token leak"},
            {"fingerprint": "fp-other", "rule_name": "Path Traversal", "message": "unrelated"},
        ],
    )
    url = VULN_URL.format(project_id=project["id"])

    assert {i["fingerprint"] for i in client.get(f"{url}?search=needle", headers=headers).json()["items"]} == {
        "fp-needle-xyz"
    }
    assert {i["fingerprint"] for i in client.get(f"{url}?search=Secret", headers=headers).json()["items"]} == {
        "fp-needle-xyz"
    }
    assert {i["fingerprint"] for i in client.get(f"{url}?search=leak", headers=headers).json()["items"]} == {
        "fp-needle-xyz"
    }


def test_list_paging_and_total_count(client):
    owner = register_and_login(client, email="vuln-page@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_and_reconcile(
        project["id"], [{"fingerprint": f"fp-{i}", "rule_name": f"Rule {i}"} for i in range(5)]
    )
    url = VULN_URL.format(project_id=project["id"])

    page1 = client.get(f"{url}?page=1&page_size=2", headers=headers).json()
    assert page1["total"] == 5
    assert len(page1["items"]) == 2

    page3 = client.get(f"{url}?page=3&page_size=2", headers=headers).json()
    assert len(page3["items"]) == 1


def test_non_member_gets_403_on_every_vulnerability_route(client):
    owner = register_and_login(client, email="vuln-403-owner@zs.dev")
    outsider = register_and_login(client, email="vuln-403-outsider@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    scan_id, findings = _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")
    out_headers = _headers(outsider)
    base = VULN_URL.format(project_id=project["id"])

    assert client.get(base, headers=out_headers).status_code == 403
    assert client.get(f"{base}/{vid}", headers=out_headers).status_code == 403
    assert (
        client.patch(f"{base}/{vid}/status", json={"status": "in_progress"}, headers=out_headers).status_code
        == 403
    )
    assert (
        client.patch(
            f"{base}/{vid}/assignment", json={"assignee_user_id": None}, headers=out_headers
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/projects/{project['id']}/scans/{scan_id}/regression", headers=out_headers
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/projects/{project['id']}/audit-log", headers=out_headers).status_code == 403


# --- status transitions -----------------------------------------------------------------


def test_resolve_without_a_reason_is_rejected(client):
    owner = register_and_login(client, email="vuln-noreason@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")

    r = client.patch(
        f"{VULN_URL.format(project_id=project['id'])}/{vid}/status",
        json={"status": "resolved"},
        headers=headers,
    )
    assert r.status_code == 400


def test_manual_fixed_without_comment_is_rejected(client):
    owner = register_and_login(client, email="vuln-nocomment@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")
    url = f"{VULN_URL.format(project_id=project['id'])}/{vid}/status"

    r = client.patch(url, json={"status": "resolved", "resolution_reason": "fixed"}, headers=headers)
    assert r.status_code == 400

    r = client.patch(
        url,
        json={"status": "resolved", "resolution_reason": "fixed", "resolution_comment": "   "},
        headers=headers,
    )
    assert r.status_code == 400

    r = client.patch(
        url,
        json={
            "status": "resolved",
            "resolution_reason": "fixed",
            "resolution_comment": "Verified in the next scan run.",
        },
        headers=headers,
    )
    assert r.status_code == 200


def test_valid_resolve_persists_and_is_audited(client):
    owner = register_and_login(client, email="vuln-resolve@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")

    r = client.patch(
        f"{VULN_URL.format(project_id=project['id'])}/{vid}/status",
        json={"status": "resolved", "resolution_reason": "duplicate"},
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "resolved"
    assert body["resolution_reason"] == "duplicate"
    assert body["resolved_at"] is not None

    admin = _admin_headers(client, email="vuln-resolve-admin@zs.dev")
    logs = client.get("/api/v1/audit-logs", headers=admin).json()["items"]
    row = next(i for i in logs if i["action"] == "Vulnerability Status Updated")
    assert row["actor_type"] == "user"
    assert row["metadata"]["status"]["after"] == "resolved"


def test_reopen_clears_resolution_fields(client):
    owner = register_and_login(client, email="vuln-reopen@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")
    url = f"{VULN_URL.format(project_id=project['id'])}/{vid}/status"

    client.patch(url, json={"status": "resolved", "resolution_reason": "wont_fix"}, headers=headers)
    r = client.patch(url, json={"status": "open"}, headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "open"
    assert body["resolution_reason"] is None
    assert body["resolution_comment"] is None
    assert body["resolved_at"] is None
    assert body["reopened_at"] is not None


def test_unknown_status_is_422(client):
    owner = register_and_login(client, email="vuln-unknown@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")

    r = client.patch(
        f"{VULN_URL.format(project_id=project['id'])}/{vid}/status",
        json={"status": "wontfix-typo"},
        headers=headers,
    )
    assert r.status_code == 422


def test_accepted_risk_leaves_first_seen_and_assignee_untouched(client):
    owner = register_and_login(client, email="vuln-accepted@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    register_and_login(client, email="vuln-accepted-collab@zs.dev")
    _invite(client, headers, project["id"], "vuln-accepted-collab@zs.dev")
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")
    base = VULN_URL.format(project_id=project["id"])

    async def _find_collab():
        from app.models.project_member import ProjectMember

        m = await ProjectMember.find_one(
            ProjectMember.project_id == project["id"], ProjectMember.invited_email == "vuln-accepted-collab@zs.dev"
        )
        return m.user_id

    collab_id = asyncio.run(_find_collab())
    client.patch(f"{base}/{vid}/assignment", json={"assignee_user_id": collab_id}, headers=headers)

    before = client.get(f"{base}/{vid}", headers=headers).json()
    r = client.patch(f"{base}/{vid}/status", json={"status": "accepted_risk"}, headers=headers)
    assert r.status_code == 200
    after = r.json()
    assert after["first_seen_at"] == before["first_seen_at"]
    assert after["assignee_user_id"] == collab_id


# --- assignment --------------------------------------------------------------------------


def test_assignment_owner_assigns_another_member(client):
    owner = register_and_login(client, email="vuln-assign-owner@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    register_and_login(client, email="vuln-assign-member@zs.dev")
    _invite(client, headers, project["id"], "vuln-assign-member@zs.dev")
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")

    async def _member_id():
        from app.models.project_member import ProjectMember

        m = await ProjectMember.find_one(
            ProjectMember.project_id == project["id"], ProjectMember.invited_email == "vuln-assign-member@zs.dev"
        )
        return m.user_id

    member_id = asyncio.run(_member_id())
    r = client.patch(
        f"{VULN_URL.format(project_id=project['id'])}/{vid}/assignment",
        json={"assignee_user_id": member_id},
        headers=headers,
    )
    assert r.status_code == 200
    assert r.json()["assignee_user_id"] == member_id


def test_collaborator_cannot_assign_someone_else(client):
    owner = register_and_login(client, email="vuln-collab-owner@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    collaborator = register_and_login(client, email="vuln-collab-user@zs.dev")
    _invite(client, headers, project["id"], "vuln-collab-user@zs.dev")
    register_and_login(client, email="vuln-collab-third@zs.dev")
    _invite(client, headers, project["id"], "vuln-collab-third@zs.dev")
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")

    async def _uid(email):
        from app.models.project_member import ProjectMember

        m = await ProjectMember.find_one(
            ProjectMember.project_id == project["id"], ProjectMember.invited_email == email
        )
        return m.user_id

    third_id = asyncio.run(_uid("vuln-collab-third@zs.dev"))
    r = client.patch(
        f"{VULN_URL.format(project_id=project['id'])}/{vid}/assignment",
        json={"assignee_user_id": third_id},
        headers=_headers(collaborator),
    )
    assert r.status_code == 403


def test_collaborator_can_assign_and_unassign_self(client):
    owner = register_and_login(client, email="vuln-self-owner@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    collaborator = register_and_login(client, email="vuln-self-collab@zs.dev")
    _invite(client, headers, project["id"], "vuln-self-collab@zs.dev")
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")

    async def _self_id():
        from app.models.project_member import ProjectMember

        m = await ProjectMember.find_one(
            ProjectMember.project_id == project["id"], ProjectMember.invited_email == "vuln-self-collab@zs.dev"
        )
        return m.user_id

    self_id = asyncio.run(_self_id())
    collab_headers = _headers(collaborator)
    url = f"{VULN_URL.format(project_id=project['id'])}/{vid}/assignment"

    r = client.patch(url, json={"assignee_user_id": self_id}, headers=collab_headers)
    assert r.status_code == 200
    assert r.json()["assignee_user_id"] == self_id

    r = client.patch(url, json={"assignee_user_id": None}, headers=collab_headers)
    assert r.status_code == 200
    assert r.json()["assignee_user_id"] is None


def test_assigning_a_non_member_is_rejected(client):
    owner = register_and_login(client, email="vuln-nonmember-owner@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    register_and_login(client, email="vuln-nonmember-outsider@zs.dev")  # never invited
    _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")

    async def _outsider_id():
        from app.models.user import User

        u = await User.find_one(User.email == "vuln-nonmember-outsider@zs.dev")
        return str(u.id)

    outsider_id = asyncio.run(_outsider_id())
    r = client.patch(
        f"{VULN_URL.format(project_id=project['id'])}/{vid}/assignment",
        json={"assignee_user_id": outsider_id},
        headers=headers,
    )
    assert r.status_code == 400


# --- regression --------------------------------------------------------------------------


def test_regression_endpoint_buckets_and_baseline(client):
    owner = register_and_login(client, email="vuln-regression@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    t0 = datetime.now(timezone.utc)

    scan1_id, _ = _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}], created_at=t0)
    r = client.get(f"/api/v1/projects/{project['id']}/scans/{scan1_id}/regression", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["has_baseline"] is False
    assert body["baseline_scan_id"] is None
    assert body["new"]["count"] == 1
    assert [i["fingerprint"] for i in body["new"]["items"]] == ["fp-a"]

    scan2_id, _ = _seed_and_reconcile(
        project["id"],
        [{"fingerprint": "fp-a"}, {"fingerprint": "fp-b"}],
        created_at=t0 + timedelta(minutes=5),
    )
    r = client.get(f"/api/v1/projects/{project['id']}/scans/{scan2_id}/regression", headers=headers)
    body = r.json()
    assert body["has_baseline"] is True
    assert body["baseline_scan_id"] == scan1_id
    assert body["new"]["count"] == 1 and body["new"]["items"][0]["fingerprint"] == "fp-b"
    assert body["unchanged"]["count"] == 1 and body["unchanged"]["items"][0]["fingerprint"] == "fp-a"

    # scan3 drops both fingerprints -- with a prior completed scan in scope, both resolve "fixed".
    scan3_id, _ = _seed_and_reconcile(project["id"], [], created_at=t0 + timedelta(minutes=10))
    r = client.get(f"/api/v1/projects/{project['id']}/scans/{scan3_id}/regression", headers=headers)
    body = r.json()
    assert body["fixed"]["count"] == 2
    assert {i["fingerprint"] for i in body["fixed"]["items"]} == {"fp-a", "fp-b"}
    assert {i["status"] for i in body["fixed"]["items"]} == {"resolved"}

    # scan4 brings fp-a back -- it reopens.
    scan4_id, _ = _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}], created_at=t0 + timedelta(minutes=15))
    r = client.get(f"/api/v1/projects/{project['id']}/scans/{scan4_id}/regression", headers=headers)
    body = r.json()
    assert body["reopened"]["count"] == 1
    assert body["reopened"]["items"][0]["fingerprint"] == "fp-a"


def test_regression_scan_not_in_project_is_404(client):
    owner = register_and_login(client, email="vuln-regression-404@zs.dev")
    headers = _headers(owner)
    project_a = _create_project(client, headers, name="A")
    project_b = _create_project(client, headers, name="B")
    scan_id, _ = _seed_and_reconcile(project_a["id"], [{"fingerprint": "fp-a"}])

    r = client.get(f"/api/v1/projects/{project_b['id']}/scans/{scan_id}/regression", headers=headers)
    assert r.status_code == 404


# --- detail ------------------------------------------------------------------------------


def test_detail_includes_observations_and_activity(client):
    owner = register_and_login(client, email="vuln-detail@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    scan1_id, findings1 = _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    scan2_id, findings2 = _seed_and_reconcile(project["id"], [{"fingerprint": "fp-a"}])
    vid = _vuln_id(project["id"], "fp-a")

    client.patch(
        f"{VULN_URL.format(project_id=project['id'])}/{vid}/status",
        json={"status": "resolved", "resolution_reason": "duplicate"},
        headers=headers,
    )

    r = client.get(f"{VULN_URL.format(project_id=project['id'])}/{vid}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    observed_scan_ids = {o["scan_id"] for o in body["observations"]}
    assert observed_scan_ids == {scan1_id, scan2_id}
    assert any(e["action"] == "Vulnerability Status Updated" for e in body["activity"])


# --- project-scoped audit log --------------------------------------------------------------


def test_project_audit_log_is_scoped_paged_and_member_gated(client):
    owner_a = register_and_login(client, email="audit-proj-a@zs.dev")
    headers_a = _headers(owner_a)
    project_a = _create_project(client, headers_a, name="Audit A")
    owner_b = register_and_login(client, email="audit-proj-b@zs.dev")
    headers_b = _headers(owner_b)
    project_b = _create_project(client, headers_b, name="Audit B")
    outsider = register_and_login(client, email="audit-proj-outsider@zs.dev")

    _seed_and_reconcile(project_a["id"], [{"fingerprint": "fp-a"}])
    vid_a = _vuln_id(project_a["id"], "fp-a")
    for i in range(3):
        client.patch(
            f"{VULN_URL.format(project_id=project_a['id'])}/{vid_a}/status",
            json={"status": "in_progress" if i % 2 == 0 else "open"},
            headers=headers_a,
        )

    _seed_and_reconcile(project_b["id"], [{"fingerprint": "fp-b"}])
    vid_b = _vuln_id(project_b["id"], "fp-b")
    client.patch(
        f"{VULN_URL.format(project_id=project_b['id'])}/{vid_b}/status",
        json={"status": "in_progress"},
        headers=headers_b,
    )

    admin = _admin_headers(client, email="audit-proj-admin@zs.dev")
    client.put("/api/v1/workspace-settings", json={"scan_enable_sca": False}, headers=admin)

    async def _real_total():
        from app.models.audit_log import AuditLog

        return await AuditLog.find(AuditLog.project_id == project_a["id"]).count()

    expected_total = asyncio.run(_real_total())
    # Project A picked up more than the 3 status updates (e.g. "Project Created" and the
    # reconciler's own "Vulnerability Reconciled" row) -- the real count, not a guessed one, is
    # what pagination and scoping are checked against.
    assert expected_total >= 3

    r = client.get(f"/api/v1/projects/{project_a['id']}/audit-log?page_size=2", headers=headers_a)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == expected_total
    assert len(body["items"]) == 2
    assert all(i["project_id"] == project_a["id"] for i in body["items"])
    assert all(i["action"] != "Workspace Settings Updated" for i in body["items"])
    all_target_ids = {i["target_id"] for i in body["items"] if i["target_id"]}

    last_page = -(-expected_total // 2)  # ceil division
    r_last = client.get(
        f"/api/v1/projects/{project_a['id']}/audit-log?page={last_page}&page_size=2", headers=headers_a
    )
    remainder = expected_total - 2 * (last_page - 1)
    assert len(r_last.json()["items"]) == remainder
    all_target_ids |= {i["target_id"] for i in r_last.json()["items"] if i["target_id"]}
    # Project B's vulnerability never surfaces under project A's log -- structurally guaranteed
    # by the project_id equality filter, but asserted directly too.
    assert vid_b not in all_target_ids

    assert (
        client.get(f"/api/v1/projects/{project_a['id']}/audit-log", headers=_headers(outsider)).status_code
        == 403
    )


# --- orphaned-comment fix -----------------------------------------------------------------


def test_comment_survives_a_rescan(client):
    """A comment keyed only by finding_id used to become unreachable the moment a rescan
    minted a new Finding ObjectId for the same recurring fingerprint. vulnerability_id is the
    durable key that fixes this."""
    owner = register_and_login(client, email="comment-rescan@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)

    scan1_id, findings1 = _seed_and_reconcile(project["id"], [{"fingerprint": "fp-x"}])
    finding1 = findings1["fp-x"]
    assert finding1.vulnerability_id  # reconcile_scan must have stamped it

    r = client.post(
        f"/api/v1/findings/{finding1.id}/comments", json={"body": "Confirmed exploitable"}, headers=headers
    )
    assert r.status_code == 200

    # Rescan: a brand-new Finding document for the identical fingerprint, sharing the same
    # Vulnerability row (and therefore the same vulnerability_id) but a different _id.
    scan2_id, findings2 = _seed_and_reconcile(project["id"], [{"fingerprint": "fp-x"}])
    finding2 = findings2["fp-x"]
    assert str(finding2.id) != str(finding1.id)
    assert finding2.vulnerability_id == finding1.vulnerability_id

    comments = client.get(f"/api/v1/findings/{finding2.id}/comments", headers=headers).json()["items"]
    assert any(c["body"] == "Confirmed exploitable" for c in comments)


def test_legacy_comment_with_no_vulnerability_id_still_renders(client):
    """Comments written before this field existed have vulnerability_id=None -- the read must
    still fall back to the legacy finding_id match for those."""
    owner = register_and_login(client, email="comment-legacy@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    scan_id, findings = _seed_and_reconcile(project["id"], [{"fingerprint": "fp-legacy"}])
    finding = findings["fp-legacy"]

    async def _insert_legacy_comment():
        await FindingComment(
            finding_id=str(finding.id),
            scan_id=scan_id,
            project_id=project["id"],
            vulnerability_id=None,
            author_user_id="000000000000000000000000",
            body="pre-fix legacy comment",
        ).insert()

    asyncio.run(_insert_legacy_comment())

    comments = client.get(f"/api/v1/findings/{finding.id}/comments", headers=headers).json()["items"]
    assert any(c["body"] == "pre-fix legacy comment" for c in comments)

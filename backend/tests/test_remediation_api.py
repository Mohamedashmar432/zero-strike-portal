"""API integration tests for AI Auto-Fix (propose phase). Mocks the agent loop
(ai_remediation_agent.run_agent) so the router + queue + service wiring is exercised
end-to-end without an LLM. Mirrors test_ai_analysis_api.py's setup helpers."""

import asyncio
import time
from datetime import datetime, timezone

import app.services.ai_remediation_agent as ai_remediation_agent
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.finding import DependencyEmbedded, EvidenceEmbedded, Finding, LocationEmbedded
from app.models.scan import Scan
from app.services import ai_remediation_queue_service
from app.services.remediation_tools import SubmitFixProposalArgs
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Fix Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _enable_ai(client, admin_headers, provider="anthropic", model="claude-haiku-4-5"):
    r = client.post(
        "/api/v1/ai/providers",
        json={"name": "P", "provider": provider, "model_name": model, "api_key": "k"},
        headers=admin_headers,
    )
    assert r.status_code == 201


def _insert_scan(project_id, branch="main"):
    async def _do():
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id=project_id, scan_type="cloud", status="completed", branch=branch,
            created_at=now, updated_at=now,
        )
        await scan.insert()
        return str(scan.id)

    return asyncio.run(_do())


def _insert_finding(project_id, scan_id, fingerprint, rule="rule-a"):
    async def _do():
        f = Finding(
            scan_id=scan_id,
            project_id=project_id,
            fingerprint=fingerprint,
            rule_id=rule,
            rule_name="SQL Injection",
            message="tainted query",
            location=LocationEmbedded(file="app.py", start_line=10, end_line=10),
            evidence=[EvidenceEmbedded(snippet="q = 'SELECT * FROM u WHERE id=' + uid", start_line=10, end_line=10)],
            severity="high",
            kind="sast",
            language="python",
            created_at=datetime.now(timezone.utc),
        )
        await f.insert()
        return str(f.id)

    return asyncio.run(_do())


def _poll_scan(client, headers, scan_id, max_iterations=100):
    body = None
    for _ in range(max_iterations):
        body = client.get(f"/api/v1/scans/{scan_id}/auto-fix", headers=headers).json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"auto-fix did not finish: {body}")


def test_trigger_409_when_no_tool_capable_provider(client):
    owner = register_and_login(client, email="fix-owner-409@zs.dev")
    project = _create_project(client, _headers(owner))
    fid = _insert_finding(project["id"], "scan-409", "fp-409")

    # No provider configured at all -> 409, no job.
    r = client.post(f"/api/v1/findings/{fid}/auto-fix", json={}, headers=_headers(owner))
    assert r.status_code == 409

    async def _count():
        return await RemediationJob.find().count()

    assert asyncio.run(_count()) == 0


def test_trigger_409_when_active_provider_not_tool_capable(client):
    # lmstudio is a local provider, deliberately excluded from remediation_tool_capable_providers.
    admin = _admin_headers(client, email="fix-admin-local@zs.dev")
    _enable_ai(client, admin, provider="lmstudio", model="local-model")
    owner = register_and_login(client, email="fix-owner-local@zs.dev")
    project = _create_project(client, _headers(owner))
    fid = _insert_finding(project["id"], "scan-loc", "fp-loc")

    r = client.post(f"/api/v1/findings/{fid}/auto-fix", json={}, headers=_headers(owner))
    assert r.status_code == 409


def test_scan_trigger_polls_to_completed_with_proposal_and_patch(client, monkeypatch):
    async def fake_run_agent(issue_bundle, ctx, budgets, revision_note=None):
        return SubmitFixProposalArgs(
            finding_id=issue_bundle["finding_id"],
            can_fix=True,
            confidence_score=95,
            file_path="app.py",
            original_code="q = 'SELECT * FROM u WHERE id=' + uid",
            patched_code="q = 'SELECT * FROM u WHERE id=%s'; params = (uid,)",
            explanation="Use a parameterized query.",
            patch_scope="single-line",
        )

    monkeypatch.setattr(ai_remediation_agent, "run_agent", fake_run_agent)

    admin = _admin_headers(client, email="fix-admin-ok@zs.dev")
    _enable_ai(client, admin)
    owner = register_and_login(client, email="fix-owner-ok@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    _insert_finding(project["id"], scan_id, "fp-ok")

    r = client.post(f"/api/v1/scans/{scan_id}/auto-fix", json={}, headers=_headers(owner))
    assert r.status_code == 200
    assert r.json()["status"] in ("queued", "in_progress", "completed")

    body = _poll_scan(client, _headers(owner), scan_id)
    assert body["status"] == "completed"
    proposals = body["insight"]["proposals"]
    assert len(proposals) == 1
    p = proposals[0]
    assert p["can_fix"] is True
    assert p["review_state"] == "proposed"
    assert p["unified_diff"] and "+q = 'SELECT * FROM u WHERE id=%s'" in p["unified_diff"]
    assert body["insight"]["summary"]["auto_fixable"] == 1

    # patch download
    patch = client.get(f"/api/v1/fix-proposals/{p['id']}/patch", headers=_headers(owner))
    assert patch.status_code == 200
    assert patch.headers["content-type"].startswith("text/x-patch")
    assert "--- a/app.py" in patch.text

    # dismiss
    d = client.post(f"/api/v1/fix-proposals/{p['id']}/dismiss", json={"reason": "not now"}, headers=_headers(owner))
    assert d.status_code == 200
    assert d.json()["review_state"] == "dismissed"


def test_cannot_fix_becomes_manual_review(client, monkeypatch):
    async def fake_run_agent(issue_bundle, ctx, budgets, revision_note=None):
        return SubmitFixProposalArgs(
            finding_id=issue_bundle["finding_id"],
            can_fix=False,
            confidence_score=0,
            file_path="app.py",
            explanation="Not enough context to fix safely.",
            patch_scope="none",
        )

    monkeypatch.setattr(ai_remediation_agent, "run_agent", fake_run_agent)

    admin = _admin_headers(client, email="fix-admin-mr@zs.dev")
    _enable_ai(client, admin)
    owner = register_and_login(client, email="fix-owner-mr@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    _insert_finding(project["id"], scan_id, "fp-mr")

    client.post(f"/api/v1/scans/{scan_id}/auto-fix", json={}, headers=_headers(owner))
    body = _poll_scan(client, _headers(owner), scan_id)
    assert body["status"] == "completed"
    p = body["insight"]["proposals"][0]
    assert p["review_state"] == "manual_review"
    assert p["manual_review_reason"]
    assert body["insight"]["summary"]["manual_review"] == 1


def test_trigger_forbidden_for_non_member(client, monkeypatch):
    admin = _admin_headers(client, email="fix-admin-forbid@zs.dev")
    _enable_ai(client, admin)
    owner = register_and_login(client, email="fix-owner-forbid@zs.dev")
    project = _create_project(client, _headers(owner))
    fid = _insert_finding(project["id"], "scan-forbid", "fp-forbid")

    outsider = register_and_login(client, email="fix-outsider@zs.dev")
    r = client.post(f"/api/v1/findings/{fid}/auto-fix", json={}, headers=_headers(outsider))
    assert r.status_code == 403


def _insert_proposal(project_id, scan_id, finding_id, can_fix=True, confidence=95):
    async def _do():
        p = AIFixProposal(
            finding_id=finding_id, scan_id=scan_id, project_id=project_id, can_fix=can_fix,
            confidence_score=confidence, original_code="a", patched_code="b", file_path="app.py",
            explanation="e", review_state="proposed",
        )
        await p.insert()
        return str(p.id)

    return asyncio.run(_do())


def test_approve_requires_owner_and_enqueues_apply(client, monkeypatch):
    # Don't actually run the write; just verify the endpoint gate + enqueue + state transition.
    async def _noop():
        return None

    monkeypatch.setattr(ai_remediation_queue_service, "drain_queue", _noop)

    owner = register_and_login(client, email="fix-owner-approve@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    fid = _insert_finding(project["id"], scan_id, "fp-approve")
    pid = _insert_proposal(project["id"], scan_id, fid)

    outsider = register_and_login(client, email="fix-outsider-approve@zs.dev")
    r = client.post(f"/api/v1/fix-proposals/{pid}/approve", json={}, headers=_headers(outsider))
    assert r.status_code == 403

    r = client.post(f"/api/v1/fix-proposals/{pid}/approve", json={}, headers=_headers(owner))
    assert r.status_code == 200
    assert r.json()["review_state"] == "approved"

    async def _apply_jobs():
        return await RemediationJob.find(
            RemediationJob.kind == "apply", RemediationJob.proposal_id == pid
        ).count()

    assert asyncio.run(_apply_jobs()) == 1


def test_project_auto_fix_list_and_breakdown(client):
    owner = register_and_login(client, email="fix-owner-list@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    f1 = _insert_finding(project["id"], scan_id, "fp-l1")
    f2 = _insert_finding(project["id"], scan_id, "fp-l2")
    f3 = _insert_finding(project["id"], scan_id, "fp-l3")
    _insert_proposal(project["id"], scan_id, f1, can_fix=True, confidence=95)  # ai_fixable
    _insert_proposal(project["id"], scan_id, f2, can_fix=True, confidence=40)  # needs_review_on_fix

    async def _mr():
        p = AIFixProposal(
            finding_id=f3, scan_id=scan_id, project_id=project["id"], can_fix=False,
            confidence_score=0, review_state="manual_review", explanation="e",
        )
        await p.insert()

    asyncio.run(_mr())  # cannot_fix

    r = client.get(f"/api/v1/projects/{project['id']}/auto-fix/scans", headers=_headers(owner))
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["scan_id"] == scan_id
    assert item["status"] == "completed"
    s = item["summary"]
    assert s["total_findings"] == 3
    assert s["ai_fixable"] == 1
    assert s["needs_review_on_fix"] == 1
    assert s["cannot_fix"] == 1
    assert s["risk_rating"] == "high"  # findings are severity "high"

    outsider = register_and_login(client, email="fix-outsider-list@zs.dev")
    r = client.get(f"/api/v1/projects/{project['id']}/auto-fix/scans", headers=_headers(outsider))
    assert r.status_code == 403


def test_finding_comments_and_scan_summary(client):
    owner = register_and_login(client, email="fix-owner-comments@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    f1 = _insert_finding(project["id"], scan_id, "fp-c1")
    f2 = _insert_finding(project["id"], scan_id, "fp-c2")

    r = client.post(f"/api/v1/findings/{f1}/comments", json={"body": "Looks right to me"}, headers=_headers(owner))
    assert r.status_code == 200
    assert r.json()["body"] == "Looks right to me"
    assert r.json()["author_email"] == "fix-owner-comments@zs.dev"

    client.post(f"/api/v1/findings/{f1}/comments", json={"body": "second"}, headers=_headers(owner))

    lst = client.get(f"/api/v1/findings/{f1}/comments", headers=_headers(owner))
    assert len(lst.json()["items"]) == 2

    summary = client.get(f"/api/v1/scans/{scan_id}/comments/summary", headers=_headers(owner)).json()
    assert summary["total"] == 2
    by = {row["finding_id"]: row["count"] for row in summary["by_finding"]}
    assert by == {f1: 2}
    assert f2 not in by

    # empty body rejected; non-member forbidden
    assert client.post(f"/api/v1/findings/{f1}/comments", json={"body": "  "}, headers=_headers(owner)).status_code == 400
    outsider = register_and_login(client, email="fix-outsider-comments@zs.dev")
    assert client.get(f"/api/v1/findings/{f1}/comments", headers=_headers(outsider)).status_code == 403


def test_auto_fix_activity_timeline(client, monkeypatch):
    async def _noop():
        return None

    monkeypatch.setattr(ai_remediation_queue_service, "drain_queue", _noop)

    owner = register_and_login(client, email="fix-owner-activity@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    fid = _insert_finding(project["id"], scan_id, "fp-act")
    pid = _insert_proposal(project["id"], scan_id, fid)

    # Approve records an "AI Fix Approved" audit event against this proposal.
    r = client.post(f"/api/v1/fix-proposals/{pid}/approve", json={}, headers=_headers(owner))
    assert r.status_code == 200

    act = client.get(f"/api/v1/scans/{scan_id}/auto-fix/activity", headers=_headers(owner))
    assert act.status_code == 200
    actions = [e["action"] for e in act.json()["items"]]
    assert "AI Fix Approved" in actions


def test_dependency_update_from_sca_finding():
    from app.services.ai_remediation_service import _dependency_update

    f = Finding(
        scan_id="s", project_id="p", fingerprint="fp", rule_id="CVE-x", rule_name="Vulnerable dependency",
        message="lodash is vulnerable", location=LocationEmbedded(file="package.json", start_line=1, end_line=1),
        severity="high", kind="sca", language="json", created_at=datetime.now(timezone.utc),
        dependency=DependencyEmbedded(
            ecosystem="npm", package="lodash", installed_version="4.17.11", fixed_version="4.17.21",
            manifest="package.json",
        ),
    )
    du = _dependency_update(f)
    assert du is not None
    assert du["package"] == "lodash"
    assert du["current_version"] == "4.17.11"
    assert du["recommended_version"] == "4.17.21"
    assert du["available_versions"] == ["4.17.21"]

    f.kind = "sast"  # non-SCA -> no picker
    assert _dependency_update(f) is None


def test_ask_appends_qa_to_conversation(client, monkeypatch):
    import app.services.ai_remediation_service as svc

    async def fake_ask(proposal, finding, question):
        return "Use a parameterized query."

    monkeypatch.setattr(svc, "ask_about_fix", fake_ask)

    owner = register_and_login(client, email="fix-owner-ask@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    fid = _insert_finding(project["id"], scan_id, "fp-ask")
    pid = _insert_proposal(project["id"], scan_id, fid)

    r = client.post(
        f"/api/v1/fix-proposals/{pid}/ask", json={"question": "How do I fix this?"}, headers=_headers(owner)
    )
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user" and msgs[0]["kind"] == "qa"
    assert msgs[1]["role"] == "assistant" and "parameterized" in msgs[1]["body"]

    # persisted and readable by another member
    g = client.get(f"/api/v1/fix-proposals/{pid}/conversation", headers=_headers(owner))
    assert len(g.json()["messages"]) == 2


def test_revise_enqueues_propose_with_note_and_records_conversation(client, monkeypatch):
    async def _noop():
        return None

    monkeypatch.setattr(ai_remediation_queue_service, "drain_queue", _noop)

    admin = _admin_headers(client, email="fix-admin-revise@zs.dev")
    _enable_ai(client, admin)  # anthropic is tool-capable
    owner = register_and_login(client, email="fix-owner-revise@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    fid = _insert_finding(project["id"], scan_id, "fp-revise")
    pid = _insert_proposal(project["id"], scan_id, fid)

    r = client.post(
        f"/api/v1/fix-proposals/{pid}/revise", json={"instruction": "use bcrypt instead"}, headers=_headers(owner)
    )
    assert r.status_code == 200
    assert r.json()["status"] in ("queued", "in_progress", "completed")

    async def _job():
        return await RemediationJob.find(
            RemediationJob.kind == "propose", RemediationJob.revision_note == "use bcrypt instead"
        ).first_or_none()

    job = asyncio.run(_job())
    assert job is not None
    assert job.finding_ids == [fid]

    g = client.get(f"/api/v1/fix-proposals/{pid}/conversation", headers=_headers(owner))
    msgs = g.json()["messages"]
    assert any(m["kind"] == "revision" and "bcrypt" in m["body"] for m in msgs)


def test_owner_can_approve_below_confidence_threshold(client, monkeypatch):
    # Confidence gates *auto*-approval only; a human owner who reviewed the diff may approve a
    # low-confidence fix. The apply job's re-scan remains the real safety gate.
    async def _noop():
        return None

    monkeypatch.setattr(ai_remediation_queue_service, "drain_queue", _noop)

    owner = register_and_login(client, email="fix-owner-lowconf@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    fid = _insert_finding(project["id"], scan_id, "fp-lowconf")
    pid = _insert_proposal(project["id"], scan_id, fid, confidence=40)  # below the 80 default

    r = client.post(f"/api/v1/fix-proposals/{pid}/approve", json={}, headers=_headers(owner))
    assert r.status_code == 200
    assert r.json()["review_state"] == "approved"

    async def _apply_jobs():
        return await RemediationJob.find(RemediationJob.kind == "apply").count()

    assert asyncio.run(_apply_jobs()) == 1  # human approval enqueues the write job


def test_repeated_runs_advance_through_a_scan_larger_than_one_batch(client, monkeypatch):
    """The batch cap bounds ONE run, not the scan.

    Regression: the trigger used to auto-select the top `max_findings_per_job` findings
    regardless of whether they already had a proposal, so every click after the first
    re-selected the same findings, the worker skipped them all as already-proposed, and
    findings below the cap were unreachable forever (verified: run 2 produced 0 new
    proposals). `uncovered_findings` is what the UI reads to say how much work is left,
    so it is asserted at every step.
    """

    async def fake_run_agent(issue_bundle, ctx, budgets, revision_note=None):
        return SubmitFixProposalArgs(
            finding_id=issue_bundle["finding_id"], can_fix=True, confidence_score=90,
            file_path="app.py", original_code="a = 1", patched_code="a = 2",
            explanation="fix", patch_scope="single-line",
        )

    monkeypatch.setattr(ai_remediation_agent, "run_agent", fake_run_agent)
    admin = _admin_headers(client, email="fix-batch-admin@zs.dev")
    _enable_ai(client, admin)
    # Two findings per run, against a 5-finding scan: three runs to cover it.
    assert client.put(
        "/api/v1/remediation-settings/settings",
        json={"max_findings_per_job": 2}, headers=admin,
    ).status_code == 200

    owner = register_and_login(client, email="fix-batch-owner@zs.dev")
    headers = _headers(owner)
    project = _create_project(client, headers, name="Batching")
    scan_id = _insert_scan(project["id"])
    for i in range(5):
        _insert_finding(project["id"], scan_id, f"fp-batch-{i}")

    for expected_covered in (2, 4, 5):
        assert client.post(
            f"/api/v1/scans/{scan_id}/auto-fix", json={}, headers=headers
        ).status_code == 200
        body = _poll_scan(client, headers, scan_id)
        assert body["status"] == "completed", body
        summary = body["insight"]["summary"]
        # The listing is the whole scan at every step -- only execution is batched.
        assert summary["total_findings"] == 5
        assert len(body["insight"]["proposals"]) == expected_covered
        assert summary["uncovered_findings"] == 5 - expected_covered
        # Nothing was re-drafted: each run spent its calls on findings it had not seen.
        assert body["skipped_existing"] == 0

    # Fully covered: the trigger refuses rather than burning a run on nothing.
    r = client.post(f"/api/v1/scans/{scan_id}/auto-fix", json={}, headers=headers)
    assert r.status_code == 400
    assert "already has a fix proposal" in r.json()["detail"]

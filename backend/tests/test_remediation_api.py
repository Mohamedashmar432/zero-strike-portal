"""API integration tests for AI Auto-Fix (propose phase). Mocks the agent loop
(ai_remediation_agent.run_agent) so the router + queue + service wiring is exercised
end-to-end without an LLM. Mirrors test_ai_analysis_api.py's setup helpers."""

import asyncio
import time
from datetime import datetime, timezone

import app.services.ai_remediation_agent as ai_remediation_agent
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.finding import EvidenceEmbedded, Finding, LocationEmbedded
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
    async def fake_run_agent(issue_bundle, ctx, budgets):
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
    async def fake_run_agent(issue_bundle, ctx, budgets):
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


def _insert_proposal(project_id, scan_id, finding_id, can_fix=True):
    async def _do():
        p = AIFixProposal(
            finding_id=finding_id, scan_id=scan_id, project_id=project_id, can_fix=can_fix,
            confidence_score=95, original_code="a", patched_code="b", file_path="app.py",
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

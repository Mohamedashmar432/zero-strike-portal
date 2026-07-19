import asyncio
import time
from datetime import datetime, timezone

import app.services.llm_client as llm_client
from app.models.ai_analysis_job import AIAnalysisJob
from app.models.ai_finding_insight import AIFindingInsight
from app.models.finding import Finding, LocationEmbedded
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="AI Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _enable_ai(client, admin_headers):
    r = client.post(
        "/api/v1/ai/providers",
        json={"name": "Test Provider", "provider": "anthropic", "model_name": "claude-haiku-4-5", "api_key": "test-key"},
        headers=admin_headers,
    )
    assert r.status_code == 201


def _insert_finding(project_id, scan_id="scan-1", fingerprint="fp-1", rule_id="rule-a"):
    async def _do():
        now = datetime.now(timezone.utc)
        finding = Finding(
            scan_id=scan_id,
            project_id=project_id,
            fingerprint=fingerprint,
            rule_id=rule_id,
            message="A finding",
            location=LocationEmbedded(file="app.py", start_line=1),
            severity="high",
            created_at=now,
        )
        await finding.insert()
        return str(finding.id)

    return asyncio.run(_do())


def _count_jobs(kind, scope_key):
    async def _do():
        return await AIAnalysisJob.find(AIAnalysisJob.kind == kind, AIAnalysisJob.scope_key == scope_key).count()

    return asyncio.run(_do())


def _enrichment_response(fingerprints):
    return {
        "findings": [
            {
                "fingerprint": fp,
                "owasp": ["A03:2021"],
                "cwe": ["CWE-89"],
                "cvss_score": 7.0,
                "explanation": "explained",
                "is_false_positive": False,
                "false_positive_confidence": 0.2,
                "verdict_reasoning": "real",
                "improved_description": "improved",
            }
            for fp in fingerprints
        ]
    }


def _poll_finding_analysis_until_terminal(client, headers, finding_id, max_iterations=50):
    body = None
    for _ in range(max_iterations):
        body = client.get(f"/api/v1/findings/{finding_id}/ai-analysis", headers=headers).json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"analysis did not reach a terminal status in time: {body}")


def test_trigger_finding_analysis_polls_to_completed_with_insight(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        return _enrichment_response(["fp-1"])

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    admin_headers = _admin_headers(client, email="ai-api-admin1@zerostrike.dev")
    _enable_ai(client, admin_headers)

    owner = register_and_login(client, email="ai-api-owner1@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    finding_id = _insert_finding(project["id"])

    r = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={}, headers=_headers(owner))
    assert r.status_code == 200
    assert r.json()["status"] in ("queued", "in_progress", "completed")

    body = _poll_finding_analysis_until_terminal(client, _headers(owner), finding_id)
    assert body["status"] == "completed"
    assert body["insight"] is not None
    assert body["insight"]["explanation"] == "explained"


def test_trigger_returns_409_when_not_configured_and_creates_no_job(client, monkeypatch):
    owner = register_and_login(client, email="ai-api-owner2@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    finding_id = _insert_finding(project["id"], fingerprint="fp-409", scan_id="scan-409")

    r = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={}, headers=_headers(owner))
    assert r.status_code == 409
    assert _count_jobs("finding", "fp-409") == 0


def test_duplicate_trigger_while_active_does_not_create_second_job(client, monkeypatch):
    calls = {"n": 0}

    async def fake_get_completion(messages, **kwargs):
        calls["n"] += 1
        # Simulate a slow call so the job is still "running" when the duplicate trigger fires.
        await asyncio.sleep(0.2)
        return _enrichment_response(["fp-dup"])

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    admin_headers = _admin_headers(client, email="ai-api-admin3@zerostrike.dev")
    _enable_ai(client, admin_headers)

    owner = register_and_login(client, email="ai-api-owner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    finding_id = _insert_finding(project["id"], fingerprint="fp-dup", scan_id="scan-dup")

    r1 = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={}, headers=_headers(owner))
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={}, headers=_headers(owner))
    assert r2.status_code == 200

    assert _count_jobs("finding", "fp-dup") == 1

    # let it finish so it doesn't leak into other tests
    _poll_finding_analysis_until_terminal(client, _headers(owner), finding_id)


def test_force_true_on_cached_finding_creates_new_job_and_overwrites_insight(client, monkeypatch):
    call_count = {"n": 0}

    async def fake_get_completion(messages, **kwargs):
        call_count["n"] += 1
        resp = _enrichment_response(["fp-force"])
        resp["findings"][0]["explanation"] = f"explained-v{call_count['n']}"
        return resp

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    admin_headers = _admin_headers(client, email="ai-api-admin4@zerostrike.dev")
    _enable_ai(client, admin_headers)

    owner = register_and_login(client, email="ai-api-owner4@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    finding_id = _insert_finding(project["id"], fingerprint="fp-force", scan_id="scan-force")

    r = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={}, headers=_headers(owner))
    assert r.status_code == 200
    first = _poll_finding_analysis_until_terminal(client, _headers(owner), finding_id)
    assert first["status"] == "completed"
    assert first["insight"]["explanation"] == "explained-v1"

    # force=False again -> cached, still v1, no new job.
    r = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={"force": False}, headers=_headers(owner))
    assert r.json()["status"] == "completed"
    assert r.json()["insight"]["explanation"] == "explained-v1"
    assert call_count["n"] == 1

    r = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={"force": True}, headers=_headers(owner))
    assert r.status_code == 200
    second = _poll_finding_analysis_until_terminal(client, _headers(owner), finding_id)
    assert second["status"] == "completed"
    assert second["insight"]["explanation"] == "explained-v2"
    assert call_count["n"] == 2
    assert _count_jobs("finding", "fp-force") == 2


def test_trigger_forbidden_for_non_member(client, monkeypatch):
    admin_headers = _admin_headers(client, email="ai-api-admin5@zerostrike.dev")
    _enable_ai(client, admin_headers)

    owner = register_and_login(client, email="ai-api-owner5@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    finding_id = _insert_finding(project["id"], fingerprint="fp-forbidden", scan_id="scan-forbidden")

    outsider = register_and_login(client, email="ai-api-outsider5@zerostrike.dev")
    r = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={}, headers=_headers(outsider))
    assert r.status_code == 403


def test_malformed_provider_response_marks_job_failed_and_insight_stays_null(client, monkeypatch):
    async def fake_get_completion(messages, **kwargs):
        return {"unexpected": "shape"}  # missing "findings" -- fails _GroupLLMResponse validation

    monkeypatch.setattr(llm_client, "get_completion", fake_get_completion)

    admin_headers = _admin_headers(client, email="ai-api-admin6@zerostrike.dev")
    _enable_ai(client, admin_headers)

    owner = register_and_login(client, email="ai-api-owner6@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    finding_id = _insert_finding(project["id"], fingerprint="fp-malformed", scan_id="scan-malformed")

    r = client.post(f"/api/v1/findings/{finding_id}/ai-analysis", json={}, headers=_headers(owner))
    assert r.status_code == 200

    body = _poll_finding_analysis_until_terminal(client, _headers(owner), finding_id)
    assert body["status"] == "failed"
    assert body["error_message"]
    assert body["insight"] is None

    async def _check_no_insight():
        return await AIFindingInsight.find_one(
            AIFindingInsight.fingerprint == "fp-malformed", AIFindingInsight.project_id == project["id"]
        )

    assert asyncio.run(_check_no_insight()) is None

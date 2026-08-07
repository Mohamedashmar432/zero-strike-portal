import asyncio
import time
from datetime import datetime, timezone

import app.services.llm_client as llm_client
from app.models.compliance_audit import ComplianceAudit
from app.models.finding import Finding, LocationEmbedded
from app.models.scan import Scan
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Compliance Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _enable_ai(client, admin_headers):
    r = client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Test Provider",
            "provider": "anthropic",
            "model_name": "claude-haiku-4-5",
            "api_key": "test-key",
        },
        headers=admin_headers,
    )
    assert r.status_code == 201


def _seed_scan_with_findings(project_id, *, status="completed", findings=None):
    """Insert a scan plus its findings directly, bypassing the scanner. Returns the scan id."""

    async def _do():
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id=project_id,
            scan_type="cloud",
            status=status,
            created_at=now,
            updated_at=now,
        )
        await scan.insert()
        for spec in findings or []:
            await Finding(
                scan_id=str(scan.id),
                project_id=project_id,
                fingerprint=spec["fingerprint"],
                rule_id=spec.get("rule_id", "rule-a"),
                message=spec.get("message", "A finding"),
                location=LocationEmbedded(file=spec.get("file", "app.py"), start_line=3),
                severity=spec.get("severity", "high"),
                kind=spec.get("kind", "sast"),
                category=spec.get("category", "injection"),
                owasp=spec.get("owasp", []),
                cwe=spec.get("cwe", []),
                created_at=now,
            ).insert()
        return str(scan.id)

    return asyncio.run(_do())


def _count_audits(project_id):
    async def _do():
        return await ComplianceAudit.find(ComplianceAudit.project_id == project_id).count()

    return asyncio.run(_do())


def _run_audit(client, headers, project_id, **body):
    payload = {"frameworks": ["soc2"], "scope": "latest", "depth": "deterministic"}
    payload.update(body)
    return client.post(
        f"/api/v1/projects/{project_id}/compliance-audits", json=payload, headers=headers
    )


def _poll_until_terminal(client, headers, audit_id, max_iterations=50):
    body = None
    for _ in range(max_iterations):
        body = client.get(f"/api/v1/compliance/audits/{audit_id}", headers=headers).json()
        if body["status"] in ("completed", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"audit did not reach a terminal status in time: {body}")


def _control(body, control_id):
    return next(c for c in body["controls"] if c["control_id"] == control_id)


# --- catalog ---


def test_frameworks_endpoint_lists_the_catalog(client):
    owner = register_and_login(client, email="comp-cat@zerostrike.dev")
    r = client.get("/api/v1/compliance/frameworks", headers=_headers(owner))
    assert r.status_code == 200
    items = r.json()["items"]
    assert {f["key"] for f in items} == {"soc2", "iso27001", "gdpr", "hipaa"}
    soc2 = next(f for f in items if f["key"] == "soc2")
    assert soc2["controls_total"] == len(soc2["controls"])
    assert 0 < soc2["assessed_total"] < soc2["controls_total"]
    assert soc2["scope_note"]
    # Manual controls must arrive flagged, with their reason, so the wizard can be honest.
    manual = [c for c in soc2["controls"] if not c["code_assessable"]]
    assert manual and all(c["manual_reason"] for c in manual)


def test_frameworks_endpoint_requires_auth(client):
    assert client.get("/api/v1/compliance/frameworks").status_code == 401


# --- running an audit ---


def test_audit_runs_to_completed_and_maps_findings_to_controls(client):
    owner = register_and_login(client, email="comp-run@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    scan_id = _seed_scan_with_findings(
        project["id"],
        findings=[
            {"fingerprint": "fp-sqli", "severity": "critical", "category": "injection"},
            {
                "fingerprint": "fp-secret",
                "severity": "medium",
                "kind": "secret",
                "category": "secret",
            },
        ],
    )

    r = _run_audit(client, headers, project["id"], frameworks=["soc2", "gdpr"])
    assert r.status_code == 202
    audit_id = r.json()["id"]

    body = _poll_until_terminal(client, headers, audit_id)
    assert body["status"] == "completed"
    assert body["scan_ids"] == [scan_id]
    assert body["findings_total"] == 2
    assert body["findings_truncated"] is False
    assert {s["framework"] for s in body["summaries"]} == {"soc2", "gdpr"}

    # Deterministic mapping: the injection finding fails secure-development, the secret
    # (which carries NO owasp code) still fails the credentials control.
    assert _control(body, "CC8.1")["status"] == "fail"
    assert _control(body, "CC6.6")["status"] == "fail"
    assert _control(body, "CC6.6")["evidence"][0]["fingerprint"] == "fp-secret"
    # Nothing matched the SSRF control, and its rationale must not overclaim.
    assert _control(body, "CC6.3")["status"] == "pass"
    assert "not proof" in _control(body, "CC6.3")["rationale"]
    # A governance control is never inferred from code.
    assert _control(body, "CC1.1")["status"] == "needs_manual_review"

    # No AI requested -> no AI prose anywhere.
    assert all(c["ai_explanation"] is None for c in body["controls"])
    assert body["ai_note"] is None


def test_audit_is_rejected_when_the_scope_has_no_completed_scans(client):
    owner = register_and_login(client, email="comp-noscan@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    # A running scan is not evidence.
    _seed_scan_with_findings(project["id"], status="running", findings=[{"fingerprint": "fp-x"}])

    r = _run_audit(client, headers, project["id"])
    assert r.status_code == 409
    assert "Run a scan first" in r.json()["detail"]
    assert _count_audits(project["id"]) == 0


def test_ai_narrative_requires_a_configured_provider(client):
    owner = register_and_login(client, email="comp-noai@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(project["id"], findings=[{"fingerprint": "fp-a"}])

    r = _run_audit(client, headers, project["id"], depth="with_ai_narrative")
    assert r.status_code == 409
    assert _count_audits(project["id"]) == 0

    # The deterministic audit still works without any AI provider at all.
    assert _run_audit(client, headers, project["id"]).status_code == 202


def test_unknown_framework_is_rejected(client):
    owner = register_and_login(client, email="comp-badfw@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(project["id"], findings=[{"fingerprint": "fp-a"}])

    r = _run_audit(client, headers, project["id"], frameworks=["pci-dss"])
    assert r.status_code == 400
    assert "pci-dss" in r.json()["detail"]
    assert _count_audits(project["id"]) == 0


def test_duplicate_trigger_returns_the_active_audit_without_creating_a_second(client, monkeypatch):
    calls = {"n": 0}

    async def slow_completion(messages, **kwargs):
        calls["n"] += 1
        await asyncio.sleep(0.3)
        return {"controls": []}

    monkeypatch.setattr(llm_client, "get_completion", slow_completion)

    admin_headers = _admin_headers(client, email="comp-dup-admin@zerostrike.dev")
    _enable_ai(client, admin_headers)
    owner = register_and_login(client, email="comp-dup@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(
        project["id"], findings=[{"fingerprint": "fp-a", "severity": "critical"}]
    )

    first = _run_audit(client, headers, project["id"], depth="with_ai_narrative")
    assert first.status_code == 202
    second = _run_audit(client, headers, project["id"], depth="with_ai_narrative")
    assert second.status_code == 202
    assert second.json()["id"] == first.json()["id"]
    assert _count_audits(project["id"]) == 1

    _poll_until_terminal(client, headers, first.json()["id"])


def test_ai_narrative_attaches_prose_to_failing_controls_only(client, monkeypatch):
    async def fake_completion(messages, **kwargs):
        return {
            "controls": [
                {
                    "control_id": "CC8.1",
                    "explanation": "Injection flaws let untrusted input reach an interpreter.",
                    "remediation": "Use parameterised queries.",
                },
                {"control_id": "not-a-control", "explanation": "ignored", "remediation": "ignored"},
            ]
        }

    monkeypatch.setattr(llm_client, "get_completion", fake_completion)

    admin_headers = _admin_headers(client, email="comp-ai-admin@zerostrike.dev")
    _enable_ai(client, admin_headers)
    owner = register_and_login(client, email="comp-ai@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(
        project["id"],
        findings=[{"fingerprint": "fp-sqli", "severity": "critical", "category": "injection"}],
    )

    r = _run_audit(client, headers, project["id"], depth="with_ai_narrative")
    body = _poll_until_terminal(client, headers, r.json()["id"])
    assert body["status"] == "completed"
    assert _control(body, "CC8.1")["ai_remediation"] == "Use parameterised queries."
    # A passing control is never narrated, and a hallucinated control id is dropped.
    assert _control(body, "CC6.3")["ai_explanation"] is None
    assert all(c["control_id"] != "not-a-control" for c in body["controls"])


def test_malformed_llm_response_still_completes_the_audit(client, monkeypatch):
    async def broken_completion(messages, **kwargs):
        raise llm_client.LLMMalformedResponseError("not json")

    monkeypatch.setattr(llm_client, "get_completion", broken_completion)

    admin_headers = _admin_headers(client, email="comp-bad-admin@zerostrike.dev")
    _enable_ai(client, admin_headers)
    owner = register_and_login(client, email="comp-bad@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(
        project["id"],
        findings=[{"fingerprint": "fp-sqli", "severity": "critical", "category": "injection"}],
    )

    r = _run_audit(client, headers, project["id"], depth="with_ai_narrative")
    body = _poll_until_terminal(client, headers, r.json()["id"])
    # The deterministic verdicts are the product; missing prose must not fail the audit.
    assert body["status"] == "completed"
    assert _control(body, "CC8.1")["status"] == "fail"
    assert _control(body, "CC8.1")["ai_explanation"] is None
    assert "unavailable" in body["ai_note"]


# --- scope ---


def test_latest_scope_uses_only_the_most_recent_completed_scan(client):
    owner = register_and_login(client, email="comp-scope@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(
        project["id"], findings=[{"fingerprint": "fp-old", "severity": "critical"}]
    )
    newer = _seed_scan_with_findings(
        project["id"], findings=[{"fingerprint": "fp-new", "severity": "low", "category": "logging"}]
    )

    latest = _poll_until_terminal(
        client, headers, _run_audit(client, headers, project["id"]).json()["id"]
    )
    assert latest["scan_ids"] == [newer]
    assert latest["findings_total"] == 1
    # The old critical injection finding is fixed as far as current posture is concerned.
    assert _control(latest, "CC8.1")["status"] == "pass"


def test_history_scope_includes_superseded_scans(client):
    owner = register_and_login(client, email="comp-hist@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(
        project["id"], findings=[{"fingerprint": "fp-old", "severity": "critical"}]
    )
    _seed_scan_with_findings(
        project["id"], findings=[{"fingerprint": "fp-new", "severity": "low", "category": "logging"}]
    )

    body = _poll_until_terminal(
        client,
        headers,
        _run_audit(client, headers, project["id"], scope="history").json()["id"],
    )
    assert len(body["scan_ids"]) == 2
    assert body["findings_total"] == 2
    assert _control(body, "CC8.1")["status"] == "fail"


# --- listing + access control ---


def test_project_audit_list_is_newest_first(client):
    owner = register_and_login(client, email="comp-list@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(project["id"], findings=[{"fingerprint": "fp-a"}])

    first = _run_audit(client, headers, project["id"]).json()["id"]
    _poll_until_terminal(client, headers, first)
    second = _run_audit(client, headers, project["id"], frameworks=["hipaa"]).json()["id"]
    _poll_until_terminal(client, headers, second)

    r = client.get(f"/api/v1/projects/{project['id']}/compliance-audits", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [i["id"] for i in body["items"]] == [second, first]
    # The list is the summary view — control bodies stay on the detail endpoint.
    assert "controls" not in body["items"][0]
    assert body["items"][0]["summaries"]


def test_non_member_cannot_run_or_read_an_audit(client):
    owner = register_and_login(client, email="comp-owner@zerostrike.dev")
    outsider = register_and_login(client, email="comp-outsider@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(project["id"], findings=[{"fingerprint": "fp-a"}])
    audit_id = _run_audit(client, headers, project["id"]).json()["id"]

    assert _run_audit(client, _headers(outsider), project["id"]).status_code == 403
    assert (
        client.get(f"/api/v1/compliance/audits/{audit_id}", headers=_headers(outsider)).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/projects/{project['id']}/compliance-audits", headers=_headers(outsider)
        ).status_code
        == 403
    )


def test_unknown_audit_id_is_404(client):
    owner = register_and_login(client, email="comp-404@zerostrike.dev")
    r = client.get(
        "/api/v1/compliance/audits/507f1f77bcf86cd799439011", headers=_headers(owner)
    )
    assert r.status_code == 404


def test_deleting_a_project_removes_its_audits(client):
    owner = register_and_login(client, email="comp-cascade@zerostrike.dev")
    headers = _headers(owner)
    project = _create_project(client, headers)
    _seed_scan_with_findings(project["id"], findings=[{"fingerprint": "fp-a"}])
    _poll_until_terminal(
        client, headers, _run_audit(client, headers, project["id"]).json()["id"]
    )
    assert _count_audits(project["id"]) == 1

    assert client.delete(f"/api/v1/projects/{project['id']}", headers=headers).status_code in (
        200,
        204,
    )
    assert _count_audits(project["id"]) == 0

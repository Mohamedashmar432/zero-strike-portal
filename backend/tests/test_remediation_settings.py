"""Admin Auto-Fix policy (RemediationSettings) + its audit trail, and the enabled gate on the
trigger endpoint. Reuses the auth/provider helpers the other remediation tests already share."""

import app.services.ai_remediation_agent as ai_remediation_agent
from app.services.remediation_tools import SubmitFixProposalArgs
from tests.test_auth_flow import register_and_login
from tests.test_remediation_api import (
    _create_project,
    _enable_ai,
    _headers,
    _insert_finding,
    _insert_scan,
    _poll_scan,
)
from tests.test_users import _admin_headers

SETTINGS_URL = "/api/v1/remediation-settings/settings"


def test_get_returns_lazy_created_defaults(client):
    admin = _admin_headers(client, email="rs-admin-defaults@zs.dev")
    r = client.get(SETTINGS_URL, headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "enabled": True,
        "confidence_threshold": 80.0,
        "max_findings_per_job": 20,
        "blocking_severities": ["critical", "high", "medium"],
    }


def test_non_admin_cannot_read_or_write(client):
    tokens = register_and_login(client, email="rs-nonadmin@zs.dev")
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get(SETTINGS_URL, headers=h).status_code == 403
    assert client.put(SETTINGS_URL, json={"enabled": False}, headers=h).status_code == 403


def test_admin_update_persists_and_is_audited(client):
    admin = _admin_headers(client, email="rs-admin-update@zs.dev")

    r = client.put(
        SETTINGS_URL,
        json={"enabled": False, "confidence_threshold": 60, "blocking_severities": ["critical"]},
        headers=admin,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["confidence_threshold"] == 60
    assert body["blocking_severities"] == ["critical"]
    assert body["max_findings_per_job"] == 20  # untouched field keeps its default

    # Persisted (fresh GET reflects the change).
    assert client.get(SETTINGS_URL, headers=admin).json()["confidence_threshold"] == 60

    # The change is in the audit trail — this doubles as a live proof auditing writes+reads.
    actions = [log["action"] for log in client.get("/api/v1/audit-logs", headers=admin).json()["items"]]
    assert "Auto-Fix Settings Updated" in actions


def test_invalid_severity_rejected(client):
    admin = _admin_headers(client, email="rs-admin-bad-sev@zs.dev")
    r = client.put(SETTINGS_URL, json={"blocking_severities": ["nope"]}, headers=admin)
    assert r.status_code == 422


def test_trigger_409_when_autofix_disabled(client):
    # An active, tool-capable provider exists (would otherwise let the trigger through), but the
    # admin has turned Auto-Fix off -> 409, distinct from the provider-not-configured 409.
    admin = _admin_headers(client, email="rs-admin-gate@zs.dev")
    _enable_ai(client, admin)
    assert client.put(SETTINGS_URL, json={"enabled": False}, headers=admin).status_code == 200

    owner = register_and_login(client, email="rs-owner-gate@zs.dev")
    project = _create_project(client, _headers(owner))
    fid = _insert_finding(project["id"], "scan-gate", "fp-gate")

    r = client.post(f"/api/v1/findings/{fid}/auto-fix", json={}, headers=_headers(owner))
    assert r.status_code == 409
    assert "disabled" in r.json()["detail"].lower()


def test_confidence_threshold_rebuckets_proposals(client, monkeypatch):
    # A proposal at confidence 70: with the default threshold (80) it's "needs review", but
    # after an admin lowers the threshold to 60 the same proposal re-buckets as confidently
    # fixable on the next read — proving the knob is applied at read time, end to end.
    async def fake_run_agent(issue_bundle, ctx, budgets, revision_note=None):
        return SubmitFixProposalArgs(
            finding_id=issue_bundle["finding_id"],
            can_fix=True,
            confidence_score=70,
            file_path="app.py",
            original_code="q = 'SELECT * FROM u WHERE id=' + uid",
            patched_code="q = 'SELECT * FROM u WHERE id=%s'; params = (uid,)",
            explanation="Use a parameterized query.",
            patch_scope="single-line",
        )

    monkeypatch.setattr(ai_remediation_agent, "run_agent", fake_run_agent)

    admin = _admin_headers(client, email="rs-admin-bucket@zs.dev")
    _enable_ai(client, admin)
    owner = register_and_login(client, email="rs-owner-bucket@zs.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _insert_scan(project["id"])
    _insert_finding(project["id"], scan_id, "fp-bucket")

    client.post(f"/api/v1/scans/{scan_id}/auto-fix", json={}, headers=_headers(owner))
    body = _poll_scan(client, _headers(owner), scan_id)
    assert body["status"] == "completed"

    summ = body["insight"]["summary"]
    assert (summ["needs_review_on_fix"], summ["ai_fixable"]) == (1, 0)

    client.put(SETTINGS_URL, json={"confidence_threshold": 60}, headers=admin)
    summ2 = client.get(f"/api/v1/scans/{scan_id}/auto-fix", headers=_headers(owner)).json()["insight"][
        "summary"
    ]
    assert (summ2["needs_review_on_fix"], summ2["ai_fixable"]) == (0, 1)

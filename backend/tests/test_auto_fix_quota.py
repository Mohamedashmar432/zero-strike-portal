"""Per-scan AI Auto-Fix quota: usage counting, enforcement, and the request/approval flow.

Reuses the setup helpers from test_remediation_api so the fixtures stay in one place.
Proposals are inserted directly rather than generated, because what is under test is the
quota arithmetic and the authorisation split — not the agent loop.
"""

import asyncio
from datetime import datetime, timezone

from app.models.ai_fix_proposal import AIFixProposal
from app.models.auto_fix_quota import ScanAutoFixQuota
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


def _insert_proposal(project_id, scan_id, finding_id):
    """A generated proposal — this is what consumes quota."""

    async def _do():
        p = AIFixProposal(
            finding_id=finding_id,
            scan_id=scan_id,
            project_id=project_id,
            can_fix=True,
            confidence_score=90.0,
            created_at=datetime.now(timezone.utc),
        )
        await p.insert()
        return str(p.id)

    return asyncio.run(_do())


def _set_extra(scan_id, project_id, extra):
    async def _do():
        q = ScanAutoFixQuota(scan_id=scan_id, project_id=project_id, extra_granted=extra)
        await q.insert()

    return asyncio.run(_do())


def _setup(client, name="Quota Demo"):
    tokens = register_and_login(client, f"quota-{name}@example.com")
    headers = _headers(tokens)
    project = _create_project(client, headers, name=name)
    scan_id = _insert_scan(project["id"])
    return headers, project, scan_id


# --- usage reporting ---------------------------------------------------------


def test_quota_starts_at_default_ten(client):
    headers, project, scan_id = _setup(client, "default")
    r = client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["default_limit"] == 10
    assert body["extra_granted"] == 0
    assert body["limit"] == 10
    assert body["used"] == 0
    assert body["remaining"] == 10
    assert body["pending_request_count"] == 0


def test_used_counts_distinct_findings_not_proposals(client):
    """Regenerating a fix for the same finding must not charge twice."""
    headers, project, scan_id = _setup(client, "distinct")
    f1 = _insert_finding(project["id"], scan_id, "fp-1")
    f2 = _insert_finding(project["id"], scan_id, "fp-2")
    # three proposals, but only two distinct findings
    _insert_proposal(project["id"], scan_id, f1)
    _insert_proposal(project["id"], scan_id, f1)
    _insert_proposal(project["id"], scan_id, f2)

    body = client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=headers).json()
    assert body["used"] == 2
    assert body["remaining"] == 8


def test_quota_is_per_scan_not_per_project(client):
    """The whole point of the design: a second scan of the same project gets a fresh 10."""
    headers, project, scan_a = _setup(client, "perscan")
    scan_b = _insert_scan(project["id"])
    for i in range(10):
        fid = _insert_finding(project["id"], scan_a, f"fp-a-{i}")
        _insert_proposal(project["id"], scan_a, fid)

    a = client.get(f"/api/v1/scans/{scan_a}/auto-fix/quota", headers=headers).json()
    b = client.get(f"/api/v1/scans/{scan_b}/auto-fix/quota", headers=headers).json()
    assert a["used"] == 10 and a["remaining"] == 0
    assert b["used"] == 0 and b["remaining"] == 10


def test_granted_extra_raises_the_ceiling(client):
    headers, project, scan_id = _setup(client, "granted")
    _set_extra(scan_id, project["id"], 15)
    body = client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=headers).json()
    assert body["extra_granted"] == 15
    assert body["limit"] == 25
    assert body["remaining"] == 25


def test_remaining_never_negative_when_default_lowered(client):
    """An admin lowering the global default must not produce a negative remaining."""
    headers, project, scan_id = _setup(client, "lowered")
    for i in range(4):
        fid = _insert_finding(project["id"], scan_id, f"fp-low-{i}")
        _insert_proposal(project["id"], scan_id, fid)
    admin = _admin_headers(client)
    assert (
        client.put(
            "/api/v1/remediation-settings/settings",
            json={"auto_fix_findings_per_scan": 2},
            headers=admin,
        ).status_code
        == 200
    )
    body = client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=headers).json()
    assert body["limit"] == 2
    assert body["used"] == 4
    assert body["remaining"] == 0


# --- request flow ------------------------------------------------------------


def test_request_requires_reason_and_sane_amount(client):
    headers, project, scan_id = _setup(client, "validate")
    base = f"/api/v1/scans/{scan_id}/auto-fix/quota/requests"
    assert client.post(base, json={"requested_additional": 5, "reason": ""}, headers=headers).status_code == 422
    assert client.post(base, json={"requested_additional": 0, "reason": "x"}, headers=headers).status_code == 422
    assert client.post(base, json={"requested_additional": 9999, "reason": "x"}, headers=headers).status_code == 422


def test_request_then_approve_raises_quota(client):
    headers, project, scan_id = _setup(client, "approve")
    r = client.post(
        f"/api/v1/scans/{scan_id}/auto-fix/quota/requests",
        json={"requested_additional": 20, "reason": "Large legacy module, 60 findings to clear."},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "pending"
    assert req["reason"].startswith("Large legacy module")

    # visible to the requester on their own scan
    mine = client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota/requests", headers=headers).json()
    assert mine["pending_count"] == 1

    admin = _admin_headers(client)
    queue = client.get("/api/v1/admin/auto-fix-quota/requests?status=pending", headers=admin).json()
    assert any(i["id"] == req["id"] for i in queue["items"])

    # admin grants less than asked
    d = client.post(
        f"/api/v1/admin/auto-fix-quota/requests/{req['id']}/decide",
        json={"approve": True, "granted_additional": 5, "decision_note": "Start with 5."},
        headers=admin,
    )
    assert d.status_code == 200, d.text
    assert d.json()["status"] == "approved"
    assert d.json()["granted_additional"] == 5

    body = client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=headers).json()
    assert body["limit"] == 15
    assert body["remaining"] == 15


def test_reject_leaves_quota_untouched(client):
    headers, project, scan_id = _setup(client, "reject")
    req = client.post(
        f"/api/v1/scans/{scan_id}/auto-fix/quota/requests",
        json={"requested_additional": 20, "reason": "please"},
        headers=headers,
    ).json()
    admin = _admin_headers(client)
    d = client.post(
        f"/api/v1/admin/auto-fix-quota/requests/{req['id']}/decide",
        json={"approve": False, "decision_note": "Split the work across scans instead."},
        headers=admin,
    )
    assert d.status_code == 200
    assert d.json()["status"] == "rejected"
    assert d.json()["granted_additional"] is None
    assert client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=headers).json()["limit"] == 10


def test_only_one_pending_request_per_scan(client):
    headers, project, scan_id = _setup(client, "onepending")
    base = f"/api/v1/scans/{scan_id}/auto-fix/quota/requests"
    body = {"requested_additional": 5, "reason": "need more"}
    assert client.post(base, json=body, headers=headers).status_code == 201
    assert client.post(base, json=body, headers=headers).status_code == 409


def test_a_decided_request_cannot_be_decided_again(client):
    headers, project, scan_id = _setup(client, "twice")
    req = client.post(
        f"/api/v1/scans/{scan_id}/auto-fix/quota/requests",
        json={"requested_additional": 5, "reason": "need more"},
        headers=headers,
    ).json()
    admin = _admin_headers(client)
    url = f"/api/v1/admin/auto-fix-quota/requests/{req['id']}/decide"
    assert client.post(url, json={"approve": True}, headers=admin).status_code == 200
    assert client.post(url, json={"approve": True}, headers=admin).status_code == 409


# --- authorisation -----------------------------------------------------------


def test_non_admin_cannot_view_or_decide_requests(client):
    headers, project, scan_id = _setup(client, "authz")
    req = client.post(
        f"/api/v1/scans/{scan_id}/auto-fix/quota/requests",
        json={"requested_additional": 5, "reason": "need more"},
        headers=headers,
    ).json()
    assert client.get("/api/v1/admin/auto-fix-quota/requests", headers=headers).status_code == 403
    r = client.post(
        f"/api/v1/admin/auto-fix-quota/requests/{req['id']}/decide",
        json={"approve": True},
        headers=headers,
    )
    assert r.status_code == 403


def test_non_member_cannot_read_another_projects_quota(client):
    headers, project, scan_id = _setup(client, "outsider")
    # Distinct address: _setup already registered quota-outsider@example.com.
    other = _headers(register_and_login(client, "quota-intruder@example.com"))
    assert client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=other).status_code == 403
    r = client.post(
        f"/api/v1/scans/{scan_id}/auto-fix/quota/requests",
        json={"requested_additional": 5, "reason": "let me in"},
        headers=other,
    )
    assert r.status_code == 403


def test_quota_endpoints_require_auth(client):
    headers, project, scan_id = _setup(client, "anon")
    assert client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota").status_code == 401
    assert client.get("/api/v1/admin/auto-fix-quota/requests").status_code == 401


# --- service-level allocation ------------------------------------------------


def test_allocate_clamps_to_remaining_and_reruns_are_free(client):
    """allocate() is what the bulk trigger uses; exercised directly for arithmetic."""
    from app.services import auto_fix_quota_service

    headers, project, scan_id = _setup(client, "allocate")
    already = [_insert_finding(project["id"], scan_id, f"fp-al-{i}") for i in range(8)]
    for fid in already:
        _insert_proposal(project["id"], scan_id, fid)
    fresh = [_insert_finding(project["id"], scan_id, f"fp-new-{i}") for i in range(5)]

    # 8 used of 10 -> only 2 of the 5 fresh findings fit, but all 8 repeats stay free
    allowed = asyncio.run(auto_fix_quota_service.allocate(scan_id, already + fresh))
    assert len(allowed) == 10
    assert set(already).issubset(set(allowed))
    assert len([f for f in allowed if f in fresh]) == 2
    # ordering preserved from the caller's priority-sorted input
    assert allowed == [f for f in already + fresh if f in set(allowed)]


def test_allocate_409s_when_exhausted_and_all_findings_are_new(client):
    import pytest
    from fastapi import HTTPException

    from app.services import auto_fix_quota_service

    headers, project, scan_id = _setup(client, "exhausted")
    for i in range(10):
        fid = _insert_finding(project["id"], scan_id, f"fp-ex-{i}")
        _insert_proposal(project["id"], scan_id, fid)
    fresh = [_insert_finding(project["id"], scan_id, "fp-ex-new")]

    with pytest.raises(HTTPException) as exc:
        asyncio.run(auto_fix_quota_service.allocate(scan_id, fresh))
    assert exc.value.status_code == 409
    assert "allowance" in exc.value.detail


# --- gaps found by measuring coverage ---------------------------------------


def test_single_finding_gate_blocks_when_exhausted_but_reruns_are_free(client):
    """assert_can_fix_one backs POST /findings/{id}/auto-fix, a different path to allocate()."""
    import pytest
    from fastapi import HTTPException

    from app.services import auto_fix_quota_service

    headers, project, scan_id = _setup(client, "onegate")
    charged = []
    for i in range(10):
        fid = _insert_finding(project["id"], scan_id, f"fp-gate-{i}")
        _insert_proposal(project["id"], scan_id, fid)
        charged.append(fid)

    # a finding that already has a proposal is free even at the limit
    asyncio.run(auto_fix_quota_service.assert_can_fix_one(scan_id, charged[0]))

    # a brand-new one is not
    fresh = _insert_finding(project["id"], scan_id, "fp-gate-new")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(auto_fix_quota_service.assert_can_fix_one(scan_id, fresh))
    assert exc.value.status_code == 409
    assert "allowance" in exc.value.detail

    # and it passes again once headroom is granted
    _set_extra(scan_id, project["id"], 5)
    asyncio.run(auto_fix_quota_service.assert_can_fix_one(scan_id, fresh))


def test_second_grant_stacks_onto_the_first(client):
    """Two approvals must ADD, not overwrite — the second hits the existing-quota branch."""
    headers, project, scan_id = _setup(client, "stack")
    admin = _admin_headers(client)
    url = f"/api/v1/scans/{scan_id}/auto-fix/quota/requests"

    for grant in (7, 5):
        req = client.post(
            url, json={"requested_additional": grant, "reason": "more please"}, headers=headers
        ).json()
        d = client.post(
            f"/api/v1/admin/auto-fix-quota/requests/{req['id']}/decide",
            json={"approve": True, "granted_additional": grant},
            headers=admin,
        )
        assert d.status_code == 200, d.text

    body = client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=headers).json()
    assert body["extra_granted"] == 12  # 7 + 5, not 5
    assert body["limit"] == 22


def test_deciding_an_unknown_request_404s(client):
    admin = _admin_headers(client)
    r = client.post(
        "/api/v1/admin/auto-fix-quota/requests/6a8f000000000000000000ff/decide",
        json={"approve": True},
        headers=admin,
    )
    assert r.status_code == 404


def test_unknown_status_filter_is_rejected(client):
    admin = _admin_headers(client)
    assert client.get("/api/v1/admin/auto-fix-quota/requests?status=bogus", headers=admin).status_code == 400
    # and the valid ones still work
    for s in ("pending", "approved", "rejected"):
        assert client.get(f"/api/v1/admin/auto-fix-quota/requests?status={s}", headers=admin).status_code == 200


def test_grant_above_the_hard_ceiling_is_rejected(client):
    """The 500 cap must hold at the DECISION layer too, not just on the request."""
    headers, project, scan_id = _setup(client, "ceiling")
    req = client.post(
        f"/api/v1/scans/{scan_id}/auto-fix/quota/requests",
        json={"requested_additional": 10, "reason": "modest ask"},
        headers=headers,
    ).json()
    admin = _admin_headers(client)
    r = client.post(
        f"/api/v1/admin/auto-fix-quota/requests/{req['id']}/decide",
        json={"approve": True, "granted_additional": 100000},
        headers=admin,
    )
    assert r.status_code == 422  # schema bound
    # request survives as pending so it can still be decided properly
    assert client.get(f"/api/v1/scans/{scan_id}/auto-fix/quota", headers=headers).json()["pending_request_count"] == 1


def test_bulk_trigger_reports_the_findings_the_quota_trimmed(client, monkeypatch):
    """A trim must never be silent: the poll response carries the count, so the UI can say
    "3 findings were not queued" instead of letting them look unfixable."""
    from app.services import ai_remediation_agent, ai_remediation_service

    async def fake_run_agent(issue_bundle, ctx, budgets, revision_note=None):
        return ai_remediation_service.SubmitFixProposalArgs(
            finding_id=issue_bundle["finding_id"], can_fix=False, confidence_score=0.0,
            file_path="app.py", explanation="no fix", patch_scope="none",
        )

    monkeypatch.setattr(ai_remediation_agent, "run_agent", fake_run_agent)
    admin = _admin_headers(client, email="quota-trim-admin@zs.dev")
    _enable_ai(client, admin)
    tokens = register_and_login(client, "quota-trim@example.com")
    headers = _headers(tokens)
    project = _create_project(client, headers, name="Quota Trim")
    scan_id = _insert_scan(project["id"])
    # 8 of the 10-finding allowance already spent, then ask for 5 more.
    for i in range(8):
        _insert_proposal(project["id"], scan_id, _insert_finding(project["id"], scan_id, f"fp-t-{i}"))
    fresh = [_insert_finding(project["id"], scan_id, f"fp-tn-{i}") for i in range(5)]

    r = client.post(
        f"/api/v1/scans/{scan_id}/auto-fix", json={"finding_ids": fresh}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = _poll_scan(client, headers, scan_id)
    assert body["quota_skipped"] == 3
    # Only what the allowance permitted was attempted: 8 already charged + 2 new = 10.
    assert len(body["insight"]["proposals"]) == 10

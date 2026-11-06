"""Risk acceptance review (docs/RISK_ACCEPT_REVIEW_AND_VULN_REDESIGN.md): any finding kind can be
accepted as a risk with a real justification, behind its own admin-review switch, and legacy rows
migrate to a pending request instead of staying silently exempt."""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models.audit_log import AuditLog
from app.models.vulnerability import Vulnerability
from app.models.workspace_settings import WorkspaceSettings
from app.services import finding_review_service, workspace_settings_service
from tests.test_finding_review import REVIEWS, RISK_COMMENT, _request, _set_review_required, _setup
from tests.test_vulnerabilities_api import _vuln_id


def _vuln(pid, fp):
    return asyncio.run(Vulnerability.find_one(Vulnerability.project_id == pid, Vulnerability.fingerprint == fp))


@pytest.mark.parametrize(
    "comment",
    [
        None,
        "   ",
        "too short to count",
        "a" * 60,  # long enough, one word
        "alpha beta gamma delta epsilon 12345 67890 11111 22222 33333",  # five real words
        "test test test test test test test test test test",  # one word repeated
        "n/a",
    ],
)
def test_validate_risk_comment_refuses_thin_justifications(comment):
    with pytest.raises(HTTPException) as e:
        finding_review_service.validate_risk_comment(comment)
    assert e.value.status_code == 422


def test_validate_risk_comment_trims_a_real_one():
    assert finding_review_service.validate_risk_comment(f"  {RISK_COMMENT}  ") == RISK_COMMENT


def test_member_can_request_accepted_risk_on_a_code_finding(client):
    member, admin, pid = _setup(client, "ra", required=True)
    r = _request(client, member, pid, "fp-sqli", status="accepted_risk", resolution_comment=RISK_COMMENT)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "open" and body["review"]["kind"] == "accepted_risk"
    assert body["review"]["status"] == "pending"

    vid = _vuln_id(pid, "fp-sqli")
    item = next(i for i in client.get(REVIEWS, headers=admin).json()["items"] if i["vulnerability_id"] == vid)
    assert item["review"]["kind"] == "accepted_risk" and item["kind_of_finding"] == "sast"
    client.post(f"{REVIEWS}/{vid}/decide", json={"decision": "accept"}, headers=admin)
    assert _vuln(pid, "fp-sqli").status == "accepted_risk"


def test_accepted_risk_needs_a_real_comment_but_false_positive_does_not(client):
    member, _admin, pid = _setup(client, "rb", required=True)
    r = _request(client, member, pid, "fp-sqli", status="accepted_risk", resolution_comment="because")
    assert r.status_code == 422 and "justification" in r.json()["detail"]
    r = _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive",
                 resolution_comment="c")
    assert r.status_code == 200  # Q4: the minimum applies to accepted risk only


def test_the_two_review_switches_are_independent(client):
    member, _admin, pid = _setup(client, "rc", required=True)
    _set_review_required(True, risk=False)  # false positives reviewed, accepted risk not
    fp = _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive",
                  resolution_comment="c").json()
    risk = _request(client, member, pid, "fp-dep", status="accepted_risk", resolution_comment=RISK_COMMENT).json()
    assert fp["review"]["status"] == "pending"
    assert risk["review"]["status"] == "accepted" and risk["status"] == "accepted_risk"
    assert risk["review"]["review_comment"] == "Auto-accepted: admin review of risk acceptance is off"

    _set_review_required(False, risk=True)  # and the other way round
    r = _request(client, member, pid, "fp-sqli", status="accepted_risk", resolution_comment=RISK_COMMENT)
    assert r.status_code == 409  # the pending false positive is a different kind of review
    assert "different kind" in r.json()["detail"]


def test_a_pending_review_of_the_other_kind_is_refused_both_ways(client):
    member, _admin, pid = _setup(client, "rd", required=True)
    _request(client, member, pid, "fp-sqli", status="accepted_risk", resolution_comment=RISK_COMMENT)
    r = _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive",
                 resolution_comment="c")
    assert r.status_code == 409


def test_status_cannot_be_reopened_while_an_exemption_is_accepted(client):
    member, _admin, pid = _setup(client, "re", required=False)
    _request(client, member, pid, "fp-sqli", status="resolved", resolution_reason="false_positive",
             resolution_comment="c")
    for target in ("open", "in_progress"):
        r = _request(client, member, pid, "fp-sqli", status=target)
        assert r.status_code == 409 and "revoke" in r.json()["detail"]
    assert _vuln(pid, "fp-sqli").status == "resolved"


def test_risk_switch_is_admin_only_and_defaults_off(client):
    member, admin, _pid = _setup(client, "rf", required=False)
    url = "/api/v1/workspace-settings"
    assert client.get(url, headers=member).json()["risk_acceptance_review_required"] is False
    assert client.put(url, json={"risk_acceptance_review_required": True}, headers=member).status_code == 403
    assert client.put(url, json={"risk_acceptance_review_required": None}, headers=admin).status_code == 422
    r = client.put(url, json={"risk_acceptance_review_required": True}, headers=admin)
    assert r.status_code == 200
    assert r.json()["risk_acceptance_review_required"] is True and r.json()["finding_review_required"] is False


# --- migrations ------------------------------------------------------------------------------------


def test_risk_toggle_is_seeded_from_the_old_switch_once(client):
    async def go():
        await workspace_settings_service.update_workspace_settings(finding_review_required=True)
        coll = WorkspaceSettings.get_pymongo_collection()
        await coll.update_many({}, {"$unset": {"risk_acceptance_review_required": ""}})
        first = await finding_review_service.migrate_risk_review_toggle()
        seeded = await workspace_settings_service.get_workspace_settings()
        await workspace_settings_service.update_workspace_settings(risk_acceptance_review_required=False)
        second = await finding_review_service.migrate_risk_review_toggle()
        return first, seeded.risk_acceptance_review_required, second, await workspace_settings_service.get_workspace_settings()

    first, seeded, second, ws = asyncio.run(go())
    assert (first, seeded, second) == (True, True, False)  # inherits True; idempotent
    assert ws.risk_acceptance_review_required is False  # an explicit value is never overwritten


def test_legacy_accepted_risks_become_pending_when_the_requester_is_known(client):
    _member, _admin, pid = _setup(client, "rg", required=False)

    async def legacy():
        now = datetime.now(timezone.utc)
        known = await Vulnerability.find_one(Vulnerability.project_id == pid, Vulnerability.fingerprint == "fp-sqli")
        unknown = await Vulnerability.find_one(Vulnerability.project_id == pid, Vulnerability.fingerprint == "fp-dep")
        for v in (known, unknown):
            v.status, v.resolution_comment = "accepted_risk", "legacy justification"
            await v.save()
        await AuditLog(
            actor_type="user", actor_user_id="u-legacy", action="Vulnerability Status Updated",
            target_type="vulnerability", target_id=str(known.id), project_id=pid,
            metadata={"status": {"before": "open", "after": "accepted_risk"}}, created_at=now,
        ).insert()
        first = await finding_review_service.migrate_unreviewed_accepted_risks()
        second = await finding_review_service.migrate_unreviewed_accepted_risks()
        return first, second

    first, second = asyncio.run(legacy())
    assert (first, second) == (2, 0)
    known, unknown = _vuln(pid, "fp-sqli"), _vuln(pid, "fp-dep")
    assert known.status == "open" and known.review.status == "pending" and known.review.kind == "accepted_risk"
    assert known.review.requested_by_user_id == "u-legacy"
    assert known.review.request_comment == "legacy justification"
    assert unknown.status == "open" and unknown.review is None  # no trail: reopened, never auto-accepted
    # Nothing is exempt until an admin accepts.
    assert asyncio.run(finding_review_service.accepted_exemptions(pid, known.repo_scope_key)) == []

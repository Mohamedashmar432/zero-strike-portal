"""Admin-sent acknowledgement of accepted risks: admin-only create, token single use / expiry / rate limit,
`not_configured` never opens SMTP, resend rotation and limits, masked recipients, re-acceptance
invalidating an acknowledgement, the Risk accepted list, and the PDF/CSV attachments."""

import asyncio
import re
import smtplib
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.notification import Notification
from app.models.risk_acknowledgement import AckItem, RiskAcknowledgementBatch
from app.services import email_service, pdf_report_service, risk_acknowledgement_service as ack_svc
from tests.test_finding_review import REVIEWS, RISK_COMMENT, _request, _setup
from tests.test_vulnerabilities_api import _invite, _vuln_id
from tests.test_auth_flow import register_and_login

PUBLIC = "/api/v1/risk-acknowledgements"


def _base(pid):
    return f"/api/v1/projects/{pid}"


def _accept_both(client, member, pid):
    """Auto-accepted (review off): one code finding and one dependency finding become accepted risks."""
    for fp in ("fp-sqli", "fp-dep"):
        r = _request(client, member, pid, fp, status="accepted_risk", resolution_comment=RISK_COMMENT)
        assert r.status_code == 200 and r.json()["review"]["status"] == "accepted"


@pytest.fixture
def mailbox(monkeypatch):
    """SMTP 'configured' but intercepted at send_email: no test may reach a real relay."""
    sent: list[dict] = []
    monkeypatch.setattr(settings, "smtp_host", "smtp.invalid")

    def fake(to, subject, text, html=None, attachments=None, timeout=None):
        if not subject.startswith("Risk acceptance acknowledgement"):
            return  # other portal mail (admin notifications) is swallowed, not recorded
        sent.append({"to": to, "subject": subject, "text": text, "attachments": attachments or []})

    monkeypatch.setattr(email_service, "send_email", fake)
    return sent


def _token(mail: dict) -> str:
    return re.search(r"#token=([\w-]+)", mail["text"]).group(1)


def _setup_sent(client, tag, mailbox, extras=()):
    member, admin, pid = _setup(client, tag, required=False)
    _accept_both(client, member, pid)
    r = client.post(f"{_base(pid)}/risk-acknowledgements", json={"extra_recipients": list(extras)}, headers=admin)
    assert r.status_code == 201, r.text
    return member, admin, pid, r.json()


def _batch(bid):
    return asyncio.run(RiskAcknowledgementBatch.get(bid))


# --- create ------------------------------------------------------------------------------------------


def test_create_is_admin_only_and_needs_accepted_risks(client):
    member, admin, pid = _setup(client, "ka", required=False)
    url = f"{_base(pid)}/risk-acknowledgements"
    assert client.post(url, json={}, headers=member).status_code == 403
    assert client.post(url, json={}, headers=admin).status_code == 409  # nothing accepted yet


def test_not_configured_never_opens_smtp_and_is_never_called_sent(client, monkeypatch):
    assert settings.smtp_host == ""

    def boom(*a, **k):
        raise AssertionError("SMTP must not be attempted when smtp_host is unset")

    monkeypatch.setattr(smtplib, "SMTP", boom)
    member, admin, pid = _setup(client, "kb", required=False)
    _accept_both(client, member, pid)
    r = client.post(f"{_base(pid)}/risk-acknowledgements", json={"extra_recipients": ["ext@example.org"]}, headers=admin)
    assert r.status_code == 201
    body = r.json()
    assert [x["delivery"] for x in body["recipients"]] == ["not_configured", "not_configured"]
    assert body["recipients_sent"] == 0 and body["state"] == "pending" and body["item_count"] == 2
    assert all(x["send_count"] == 0 and x["last_sent_at"] is None for x in body["recipients"])
    assert "token" not in r.text.lower().replace("token_expires_at", "")

    # Audit rows name counts, never an address; the owner (and only the owner) is told in-app.
    rows = asyncio.run(AuditLog.find(AuditLog.action == "Risk Acknowledgement Requested").to_list())
    assert len(rows) == 1 and rows[0].metadata == {"items": 2, "recipients": 2, "extra_recipients": 1}
    assert "example.org" not in str(rows[0].metadata)
    notes = asyncio.run(Notification.find(Notification.event == "risk.acknowledgement_requested").to_list())
    assert len(notes) == 1
    owner_id = client.get("/api/v1/users/me", headers=member).json()["id"]
    assert notes[0].user_id == owner_id


def test_configured_smtp_sends_pdf_and_csv_with_a_fragment_link(client, mailbox):
    _member, _admin, pid, body = _setup_sent(client, "kc", mailbox, extras=["ext@example.org", "EXT@example.org"])
    assert [m["to"] for m in mailbox] == ["member-kc@zs.dev", "ext@example.org"]  # deduped, lowercased
    assert [x["delivery"] for x in body["recipients"]] == ["sent", "sent"]
    mail = mailbox[0]
    assert [a[0] for a in mail["attachments"]] == ["risk-acceptance-report.pdf", "risk-acceptance-report.csv"]
    assert mail["attachments"][0][1][:4] == b"%PDF" and mail["attachments"][1][1][:3] == b"\xef\xbb\xbf"
    assert "/acknowledge-risk#token=" in mail["text"]
    assert _token(mailbox[0]) != _token(mailbox[1])
    # The raw token is stored nowhere.
    stored = _batch(body["id"]).model_dump_json()
    assert _token(mailbox[0]) not in stored


def test_hanging_smtp_is_bounded_and_recorded_failed(client, monkeypatch):
    """An unreachable relay must not hold the request open, and nobody is called 'sent'."""
    import time

    monkeypatch.setattr(settings, "smtp_host", "smtp.invalid")
    monkeypatch.setattr(ack_svc, "SEND_BUDGET_SECONDS", 0.3)

    def hang(*a, **k):
        time.sleep(1.0)

    monkeypatch.setattr(email_service, "send_email", hang)
    member, admin, pid = _setup(client, "kh", required=False)
    _accept_both(client, member, pid)
    started = time.monotonic()
    r = client.post(f"{_base(pid)}/risk-acknowledgements", json={"extra_recipients": ["ext@example.org"]}, headers=admin)
    assert r.status_code == 201, r.text
    assert time.monotonic() - started < 3
    body = r.json()
    assert [x["delivery"] for x in body["recipients"]] == ["failed", "failed"]
    assert body["recipients_sent"] == 0


def test_send_email_passes_the_socket_timeout_to_smtp(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.invalid")
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, **kw):
            seen.update(kw)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k): ...
        def login(self, *a): ...
        def sendmail(self, *a): ...

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    email_service.send_email("a@example.org", "s", "t", timeout=5.0)
    assert seen == {"timeout": 5.0}


def test_extra_recipients_are_validated_and_capped(client, mailbox):
    member, admin, pid = _setup(client, "kd", required=False)
    _accept_both(client, member, pid)
    url = f"{_base(pid)}/risk-acknowledgements"
    assert client.post(url, json={"extra_recipients": ["not-an-address"]}, headers=admin).status_code == 422
    eleven = [f"x{i}@example.org" for i in range(11)]
    assert client.post(url, json={"extra_recipients": eleven}, headers=admin).status_code == 422
    assert client.post(url, json={"extra_recipients": eleven[:10]}, headers=admin).status_code == 201


# --- token flow --------------------------------------------------------------------------------------


def test_link_acknowledgement_is_single_use_and_needs_no_sign_in(client, mailbox):
    _member, admin, pid, body = _setup_sent(client, "ke", mailbox)
    tok = _token(mailbox[0])
    r = client.post(f"{PUBLIC}/lookup", json={"token": tok})  # no Authorization header
    assert r.status_code == 200
    look = r.json()
    assert look["item_count"] == 2 and look["project_name"] == "Review ke"
    assert "email" not in str(look["items"][0]).lower()  # no addresses on a public page

    assert client.post(f"{PUBLIC}/acknowledge", json={"token": tok}).json()["acknowledged"] is True
    again = client.post(f"{PUBLIC}/acknowledge", json={"token": tok})
    assert again.status_code == 404
    assert client.post(f"{PUBLIC}/lookup", json={"token": tok}).status_code == 404

    detail = client.get(f"{_base(pid)}/risk-acknowledgements/{body['id']}", headers=admin).json()
    assert detail["state"] == "acknowledged" and detail["recipients_acknowledged"] == 1
    assert detail["recipients"][0]["acknowledged_via"] == "link"
    assert asyncio.run(AuditLog.find(AuditLog.action == "Risk Acknowledged").count()) == 1
    admin_notes = asyncio.run(Notification.find(Notification.event == "risk.acknowledged").to_list())
    assert len(admin_notes) >= 1


def test_every_bad_token_gets_the_same_404(client, mailbox):
    _member, _admin, _pid, body = _setup_sent(client, "kf", mailbox)
    expired = _token(mailbox[0])

    async def lapse():
        b = await RiskAcknowledgementBatch.get(body["id"])
        b.recipients[0].token_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await b.save()

    asyncio.run(lapse())
    answers = {
        (r.status_code, r.text)
        for r in (
            client.post(f"{PUBLIC}/acknowledge", json={"token": "nope"}),
            client.post(f"{PUBLIC}/acknowledge", json={"token": expired}),
            client.post(f"{PUBLIC}/lookup", json={"token": "x" * 80}),
        )
    }
    assert len(answers) == 1 and next(iter(answers))[0] == 404
    assert asyncio.run(AuditLog.find(AuditLog.action == "Risk Acknowledgement Link Expired").count()) >= 1


def test_public_routes_are_rate_limited_per_ip(client):
    codes = [client.post(f"{PUBLIC}/lookup", json={"token": f"bad{i}"}).status_code for i in range(12)]
    assert codes[:10] == [404] * 10 and codes[10:] == [429, 429]


# --- resend ------------------------------------------------------------------------------------------


def test_resend_is_throttled_rotates_the_token_and_is_capped(client, mailbox):
    _member, admin, pid, body = _setup_sent(client, "kg", mailbox)
    url = f"{_base(pid)}/risk-acknowledgements/{body['id']}/resend"
    old = _token(mailbox[0])
    assert client.post(url, headers=admin).status_code == 429  # sent seconds ago

    async def age(count=None):
        b = await RiskAcknowledgementBatch.get(body["id"])
        for r in b.recipients:
            r.last_sent_at = datetime.now(timezone.utc) - timedelta(minutes=11)
            if count is not None:
                r.send_count = count
        await b.save()

    asyncio.run(age())
    r = client.post(url, headers=admin)
    assert r.status_code == 200 and r.json()["recipients"][0]["send_count"] == 2
    new = _token(mailbox[-1])
    assert new != old
    assert client.post(f"{PUBLIC}/lookup", json={"token": old}).status_code == 404  # rotated away
    assert client.post(f"{PUBLIC}/lookup", json={"token": new}).status_code == 200

    asyncio.run(age(count=5))
    assert client.post(url, headers=admin).status_code == 409  # five sends is the cap
    assert asyncio.run(AuditLog.find(AuditLog.action == "Risk Acknowledgement Resent").count()) == 1


def test_resend_is_admin_only(client, mailbox):
    member, _admin, pid, body = _setup_sent(client, "kh", mailbox)
    assert client.post(f"{_base(pid)}/risk-acknowledgements/{body['id']}/resend", headers=member).status_code == 403


# --- reads, masking, portal acknowledge --------------------------------------------------------------


def test_members_see_masked_recipients_and_admins_see_them_whole(client, mailbox):
    member, admin, pid, _body = _setup_sent(client, "ki", mailbox, extras=["ext@example.org"])
    url = f"{_base(pid)}/risk-acknowledgements"
    masked = client.get(url, headers=member).json()["items"][0]["recipients"]
    assert [r["email"] for r in masked] == ["m***@z***.dev", "e***@e***.org"]
    full = client.get(url, headers=admin).json()["items"][0]["recipients"]
    assert [r["email"] for r in full] == ["member-ki@zs.dev", "ext@example.org"]
    stranger = register_and_login(client, email="stranger-ki@zs.dev")
    assert client.get(url, headers={"Authorization": f"Bearer {stranger['access_token']}"}).status_code == 403


def test_only_the_project_owner_acknowledges_in_the_portal(client, mailbox):
    member, admin, pid, body = _setup_sent(client, "kj", mailbox)
    collab = register_and_login(client, email="collab-kj@zs.dev")
    _invite(client, member, pid, "collab-kj@zs.dev")
    collab_h = {"Authorization": f"Bearer {collab['access_token']}"}
    url = f"{_base(pid)}/risk-acknowledgements/{body['id']}/acknowledge"
    assert client.post(url, headers=collab_h).status_code == 403
    assert client.post(url, headers=admin).status_code == 403  # an admin cannot do it for the owner
    r = client.post(url, headers=member)
    assert r.status_code == 200 and r.json()["state"] == "acknowledged"
    assert r.json()["recipients"][0]["acknowledged_via"] == "portal"
    assert client.post(url, headers=member).status_code == 409


def test_re_accepting_a_finding_supersedes_the_acknowledgement(client, mailbox):
    member, admin, pid, body = _setup_sent(client, "kk", mailbox)
    client.post(f"{_base(pid)}/risk-acknowledgements/{body['id']}/acknowledge", headers=member)
    detail_url = f"{_base(pid)}/risk-acknowledgements/{body['id']}"
    assert client.get(detail_url, headers=member).json()["state"] == "acknowledged"

    vid = _vuln_id(pid, "fp-sqli")
    client.post(f"{REVIEWS}/{vid}/revoke", json={"comment": "scope changed"}, headers=admin)
    after_revoke = client.get(detail_url, headers=member).json()
    assert after_revoke["state"] == "superseded" and after_revoke["items_superseded"] == 1

    _request(client, member, pid, "fp-sqli", status="accepted_risk", resolution_comment=RISK_COMMENT)  # re-accept
    again = client.get(detail_url, headers=member).json()
    assert again["state"] == "superseded"  # a new decision: the old acknowledgement never covers it
    assert [i["current"] for i in again["items"]].count(False) == 1


def test_risk_acceptances_list_reports_requested_approved_and_acknowledged(client, mailbox):
    member, admin, pid = _setup(client, "kl", required=False)
    _accept_both(client, member, pid)
    url = f"{_base(pid)}/risk-acceptances"
    first = client.get(url, headers=member).json()
    assert first["total"] == 2 and first["accepted_count"] == 2 and first["unacknowledged_count"] == 2
    row = first["items"][0]
    assert row["review_status"] == "accepted" and row["auto_accepted"] is True
    assert row["requested_by_email"] == "member-kl@zs.dev" and row["comment"] == RISK_COMMENT
    assert row["ack_state"] == "none" and first["latest_batch"] is None

    created = client.post(f"{_base(pid)}/risk-acknowledgements", json={}, headers=admin).json()
    awaiting = client.get(url, headers=member).json()
    assert {r["ack_state"] for r in awaiting["items"]} == {"awaiting"}
    assert awaiting["latest_batch"]["id"] == created["id"]

    client.post(f"{_base(pid)}/risk-acknowledgements/{created['id']}/acknowledge", headers=member)
    done = client.get(url, headers=member).json()
    assert {r["ack_state"] for r in done["items"]} == {"acknowledged"} and done["unacknowledged_count"] == 0
    assert done["items"][0]["acknowledged_by"] == "m***@z***.dev"
    # A pending request appears too, and the status filter narrows.
    assert client.get(url, params={"review_status": "pending"}, headers=member).json()["total"] == 0
    assert client.get(url, params={"review_status": "bogus"}, headers=member).status_code == 422


# --- reports -----------------------------------------------------------------------------------------


def test_report_previews_are_admin_only_pdf_and_csv(client):
    member, admin, pid = _setup(client, "km", required=False)
    _accept_both(client, member, pid)
    pdf = f"{_base(pid)}/risk-acceptances/report.pdf"
    csv_url = f"{_base(pid)}/risk-acceptances/report.csv"
    assert client.get(pdf, headers=member).status_code == 403 and client.get(csv_url, headers=member).status_code == 403
    r = client.get(pdf, headers=admin)
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and "attachment" in r.headers["content-disposition"]
    r = client.get(csv_url, headers=admin)
    assert r.status_code == 200 and r.content[:3] == b"\xef\xbb\xbf" and "text/csv" in r.headers["content-type"]
    assert RISK_COMMENT in r.content.decode("utf-8-sig")


def _items(n, comment="x"):
    now = datetime.now(timezone.utc)
    return [
        AckItem(
            vulnerability_id=str(i), fingerprint=f"fp{i}", rule_name=f"Rule {i}", severity="high", kind="sast",
            file_path=f"src/very/long/path/{i}/file_with_a_long_name.py", requested_by_user_id="u",
            requested_by_email="a@example.org", requested_at=now, reviewed_by_email="b@example.org",
            reviewed_at=now, comment=comment,
        )
        for i in range(n)
    ]


def test_pdf_renders_600_rows_with_long_and_non_latin_comments():
    long_comment = ("Accepted because the gateway blocks it. " * 80) + " 日本語 — “quoted”"
    pdf = asyncio.run(pdf_report_service.render_risk_acceptance_pdf("Project — 日本", _items(600, long_comment)))
    assert pdf[:4] == b"%PDF"
    html = pdf_report_service.render_risk_acceptance_html("P", _items(1, long_comment))
    assert "(truncated; see the CSV)" in html and "<pre" not in html


def test_csv_defuses_spreadsheet_formulas():
    items = _items(1, comment='=HYPERLINK("http://evil","x")')
    items[0].file_path = "+cmd|' /C calc'!A0"
    text = ack_svc.render_csv(items).decode("utf-8-sig")
    assert "'=HYPERLINK" in text and "'+cmd" in text


def test_attachment_subtype_follows_the_extension(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.invalid")
    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def sendmail(self, frm, to, msg):
            captured["msg"] = msg

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    email_service.send_email("a@example.org", "s", "t", attachments=[("r.pdf", b"%PDF-1"), ("r.csv", b"a,b")])
    assert "application/pdf" in captured["msg"] and "application/csv" in captured["msg"]

import asyncio

import pytest

import app.services.email_service as email_service
from app.core import email_templates
from app.core.config import settings
from app.services import workspace_settings_service
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

PW = "hunter2pass"


@pytest.fixture()
def sent(monkeypatch):
    """Every email handed to send_email: (to, subject, text, html)."""
    box: list[tuple] = []
    monkeypatch.setattr(
        email_service, "send_email", lambda to, subject, text, html=None: box.append((to, subject, text, html))
    )
    return box


def _require_approval(client, headers, **extra):
    r = client.put(
        "/api/v1/workspace-settings", json={"signup_requires_approval": True, **extra}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r


def _signup(client, email):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": PW, "name": "Pat <b>Doe</b>"})
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, email, password=PW):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_pending_signup_cannot_log_in_and_sees_a_clear_message(client, sent):
    admin = _admin_headers(client, email="sa-admin1@zerostrike.dev")
    _require_approval(client, admin)

    body = _signup(client, "sa-pending1@zerostrike.dev")
    assert body["approval_status"] == "pending"

    r = _login(client, "sa-pending1@zerostrike.dev")
    assert r.status_code == 403
    assert "awaiting administrator approval" in r.json()["detail"]

    # A wrong password must not reveal that the address is pending.
    r = _login(client, "sa-pending1@zerostrike.dev", password="wrong-password")
    assert r.status_code == 401


def test_approve_lets_user_in_and_emails_them_once(client, sent):
    admin = _admin_headers(client, email="sa-admin2@zerostrike.dev")
    _require_approval(client, admin)
    uid = _signup(client, "sa-pending2@zerostrike.dev")["id"]

    pending = client.get("/api/v1/users?approval_status=pending", headers=admin).json()
    assert [u["id"] for u in pending["items"]] == [uid]

    r = client.post(f"/api/v1/users/{uid}/approve", headers=admin)
    assert r.status_code == 200 and r.json()["approval_status"] == "approved"
    assert _login(client, "sa-pending2@zerostrike.dev").status_code == 200

    approved_mail = [m for m in sent if m[0] == "sa-pending2@zerostrike.dev"]
    assert len(approved_mail) == 1
    assert "approved" in approved_mail[0][1].lower()

    # Idempotent: a second click must not email the applicant again.
    client.post(f"/api/v1/users/{uid}/approve", headers=admin)
    assert len([m for m in sent if m[0] == "sa-pending2@zerostrike.dev"]) == 1


def test_reject_blocks_login_and_reason_reaches_the_applicant(client, sent):
    admin = _admin_headers(client, email="sa-admin3@zerostrike.dev")
    _require_approval(client, admin)
    uid = _signup(client, "sa-pending3@zerostrike.dev")["id"]

    r = client.post(f"/api/v1/users/{uid}/reject", json={"reason": "Not on the contractor list"}, headers=admin)
    assert r.status_code == 200 and r.json()["approval_status"] == "rejected"

    r = _login(client, "sa-pending3@zerostrike.dev")
    assert r.status_code == 403 and "not approved" in r.json()["detail"]
    mail = [m for m in sent if m[0] == "sa-pending3@zerostrike.dev"]
    assert len(mail) == 1 and "Not on the contractor list" in mail[0][2]


def test_cannot_reject_an_approved_account(client, sent):
    admin = _admin_headers(client, email="sa-admin4@zerostrike.dev")
    tokens = register_and_login(client, email="sa-live4@zerostrike.dev")
    uid = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()["id"]
    assert client.post(f"/api/v1/users/{uid}/reject", headers=admin).status_code == 409


def test_non_admin_cannot_approve(client, sent):
    tokens = register_and_login(client, email="sa-plain5@zerostrike.dev")
    h = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.post("/api/v1/users/000000000000000000000000/approve", headers=h).status_code == 403


def test_approval_is_not_enforced_while_no_admin_exists(client, sent):
    # Bootstrapping: the first account must be creatable so it can become the admin.
    asyncio.run(workspace_settings_service.update_workspace_settings(signup_requires_approval=True))
    assert _signup(client, "sa-first6@zerostrike.dev")["approval_status"] == "approved"


def test_only_chosen_admins_are_told_about_a_signup(client, sent):
    a = _admin_headers(client, email="sa-adminA@zerostrike.dev")
    b = _admin_headers(client, email="sa-adminB@zerostrike.dev")
    a_id = client.get("/api/v1/users/me", headers=a).json()["id"]
    _require_approval(client, a, signup_notify_admin_ids=[a_id])

    _signup(client, "sa-applicant7@zerostrike.dev")

    def events(h):
        return [n["event"] for n in client.get("/api/v1/notifications", headers=h).json()["items"]]

    assert "user.signup_requested" in events(a)
    assert "user.signup_requested" not in events(b)


def test_reviewers_must_be_active_admins(client, sent):
    admin = _admin_headers(client, email="sa-admin8@zerostrike.dev")
    tokens = register_and_login(client, email="sa-plain8@zerostrike.dev")
    plain_id = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()["id"]
    r = client.put("/api/v1/workspace-settings", json={"signup_notify_admin_ids": [plain_id]}, headers=admin)
    assert r.status_code == 422


def test_template_override_reset_and_validation(client, sent, monkeypatch):
    monkeypatch.setattr("app.routers.workspace_settings.settings.smtp_host", "")
    admin = _admin_headers(client, email="sa-admin9@zerostrike.dev")
    url = "/api/v1/workspace-settings/email-templates/signup_approved"

    r = client.put(url, json={"subject": "Hi {nmae}", "body": "x"}, headers=admin)
    assert r.status_code == 422 and "{nmae}" in r.json()["detail"]

    r = client.put(url, json={"subject": "Welcome aboard", "body": "Go: {action_url}"}, headers=admin)
    assert r.status_code == 200 and r.json()["subject"] == "Welcome aboard"

    r = client.put(url, json={}, headers=admin)  # blank = reset
    assert r.json()["subject"] is None

    assert client.post(url + "/test", headers=admin).status_code == 409  # SMTP unset in tests
    assert client.put("/api/v1/workspace-settings/email-templates/nope", json={}, headers=admin).status_code == 404


def test_render_escapes_html_and_strips_header_newlines():
    subject, text, html = email_templates.render(
        "signup_requested",
        {"signup_requested": {"subject": "Request: {name}"}},
        {"name": "<script>x</script>\nBcc: evil@x.com", "email": "a@b.co", "action_url": "https://p/x?a=1&b=2"},
    )
    assert "\n" not in subject
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert 'href="https://p/x?a=1&amp;b=2"' in html
    assert "<script>" in text  # plain text is not HTML; nothing to escape


def test_notify_sends_the_custom_email_to_chosen_reviewers(client, sent):
    """The in-app row is written before the email is scheduled, so a crash in the email leg
    is invisible to a notifications-only assertion. Drive the sender directly."""
    from app.services import notification_service

    asyncio.run(
        notification_service._send_emails(
            ["rev@example.test"], "t", "b", None, ("Custom subject", "plain", "<p>html</p>")
        )
    )
    assert sent == [("rev@example.test", "Custom subject", "plain", "<p>html</p>")]


def test_open_signup_sends_one_welcome_email_linking_frontend_origin(client, sent, monkeypatch):
    monkeypatch.setattr(settings, "frontend_origin", "https://portal.zerostrike.dev")
    _signup(client, "sa-welcome1@zerostrike.dev")

    mail = [m for m in sent if m[0] == "sa-welcome1@zerostrike.dev"]
    assert len(mail) == 1
    assert mail[0][1] == "Welcome to thinkShield Portal"
    assert "https://portal.zerostrike.dev/login" in mail[0][2]


def test_pending_signup_gets_no_welcome_email(client, sent):
    admin = _admin_headers(client, email="sa-admin-w2@zerostrike.dev")
    _require_approval(client, admin)
    _signup(client, "sa-welcome2@zerostrike.dev")

    assert [m for m in sent if m[0] == "sa-welcome2@zerostrike.dev"] == []


def test_welcome_email_failure_still_returns_201_and_alerts_admins(client, monkeypatch):
    admin = _admin_headers(client, email="sa-admin-w3@zerostrike.dev")

    def broken(*args, **kwargs):
        raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(email_service, "send_email", broken)
    body = _signup(client, "sa-welcome3@zerostrike.dev")

    assert body["approval_status"] == "approved"
    notes = client.get("/api/v1/notifications", headers=admin).json()["items"]
    assert any(n["event"] == "email.delivery_failed" for n in notes)

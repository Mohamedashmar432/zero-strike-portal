import asyncio
from datetime import datetime, timedelta, timezone

import app.services.email_service as email_service
from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.user import User
from tests.test_auth_flow import register_and_login


def _capture_send(monkeypatch, captured):
    def fake_send_password_reset_email(to_address, reset_url, ttl_minutes):
        captured["to_address"] = to_address
        captured["reset_url"] = reset_url
        captured["ttl_minutes"] = ttl_minutes

    # Patch at the module auth_service calls through (email_service.send_password_reset_email),
    # not smtplib directly — this is the seam auth_service actually calls.
    monkeypatch.setattr(email_service, "send_password_reset_email", fake_send_password_reset_email)


def _extract_token(reset_url: str) -> str:
    return reset_url.split("token=", 1)[1]


def test_unknown_email_returns_generic_message_and_does_not_send(client, monkeypatch):
    captured = {}
    _capture_send(monkeypatch, captured)

    r = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@zerostrike.dev"})

    assert r.status_code == 200
    assert r.json()["message"] == "If that email is registered, a reset link has been sent."
    assert captured == {}


def test_known_email_sends_reset_email_and_token_resets_password(client, monkeypatch):
    captured = {}
    _capture_send(monkeypatch, captured)
    register_and_login(client, email="forgot1@zerostrike.dev", password="oldpassword1")

    r = client.post("/api/v1/auth/forgot-password", json={"email": "forgot1@zerostrike.dev"})
    assert r.status_code == 200
    assert r.json()["message"] == "If that email is registered, a reset link has been sent."

    assert captured["to_address"] == "forgot1@zerostrike.dev"
    assert "token=" in captured["reset_url"]
    assert captured["ttl_minutes"] == settings.password_reset_token_ttl_minutes
    token = _extract_token(captured["reset_url"])

    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "newpassword1"})
    assert r.status_code == 200

    r = client.post(
        "/api/v1/auth/login", json={"email": "forgot1@zerostrike.dev", "password": "oldpassword1"}
    )
    assert r.status_code == 401

    r = client.post(
        "/api/v1/auth/login", json={"email": "forgot1@zerostrike.dev", "password": "newpassword1"}
    )
    assert r.status_code == 200


def test_expired_token_is_rejected(client, monkeypatch):
    captured = {}
    _capture_send(monkeypatch, captured)
    register_and_login(client, email="forgot2@zerostrike.dev", password="oldpassword1")
    client.post("/api/v1/auth/forgot-password", json={"email": "forgot2@zerostrike.dev"})
    token = _extract_token(captured["reset_url"])

    async def backdate_expiry():
        user = await User.find_one(User.email == "forgot2@zerostrike.dev")
        user.password_reset_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await user.save()

    asyncio.run(backdate_expiry())

    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "newpassword1"})
    assert r.status_code == 400


def test_reset_token_is_single_use(client, monkeypatch):
    captured = {}
    _capture_send(monkeypatch, captured)
    register_and_login(client, email="forgot3@zerostrike.dev", password="oldpassword1")
    client.post("/api/v1/auth/forgot-password", json={"email": "forgot3@zerostrike.dev"})
    token = _extract_token(captured["reset_url"])

    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "newpassword1"})
    assert r.status_code == 200

    r = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "anotherpassword1"}
    )
    assert r.status_code == 400


def test_unknown_token_is_rejected(client):
    r = client.post(
        "/api/v1/auth/reset-password", json={"token": "not-a-real-token", "new_password": "newpassword1"}
    )
    assert r.status_code == 400


def test_reset_password_revokes_existing_refresh_tokens(client, monkeypatch):
    captured = {}
    _capture_send(monkeypatch, captured)
    tokens = register_and_login(client, email="forgot4@zerostrike.dev", password="oldpassword1")
    old_refresh_token = tokens["refresh_token"]

    client.post("/api/v1/auth/forgot-password", json={"email": "forgot4@zerostrike.dev"})
    token = _extract_token(captured["reset_url"])

    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "newpassword1"})
    assert r.status_code == 200

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert r.status_code == 401


def test_reset_password_records_audit_log(client, monkeypatch):
    captured = {}
    _capture_send(monkeypatch, captured)
    tokens = register_and_login(client, email="forgot5@zerostrike.dev", password="oldpassword1")
    user_id = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()["id"]

    client.post("/api/v1/auth/forgot-password", json={"email": "forgot5@zerostrike.dev"})
    token = _extract_token(captured["reset_url"])

    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "newpassword1"})
    assert r.status_code == 200

    async def fetch_logs():
        return await AuditLog.find(
            AuditLog.actor_user_id == user_id, AuditLog.action == "password_reset"
        ).to_list()

    logs = asyncio.run(fetch_logs())
    assert len(logs) == 1


def test_forgot_password_is_audited_without_storing_the_email(client, monkeypatch):
    _capture_send(monkeypatch, {})
    register_and_login(client, email="forgot-audit@zerostrike.dev", password="oldpassword1")

    client.post("/api/v1/auth/forgot-password", json={"email": "forgot-audit@zerostrike.dev"})
    client.post("/api/v1/auth/forgot-password", json={"email": "nobody-audit@zerostrike.dev"})

    logs = asyncio.run(AuditLog.find().to_list())
    known = [r for r in logs if r.action == "Password Reset Requested"]
    unknown = [r for r in logs if r.action == "Password Reset Requested For Unknown Account"]
    assert len(known) == 1 and known[0].target_type == "user" and known[0].actor_user_id
    assert len(unknown) == 1 and unknown[0].actor_type == "anonymous"
    reset_rows = [r.model_dump() for r in logs if r.action.startswith("Password Reset")]
    assert "zerostrike.dev" not in str(reset_rows)


def test_reset_email_failure_keeps_the_response_and_alerts_admins(client, monkeypatch):
    from app.services import notification_service
    from tests.test_users import _admin_headers

    monkeypatch.setattr(notification_service, "_last_email_failure_alert", None)
    admin = _admin_headers(client, email="forgot-fail-admin@zerostrike.dev")
    register_and_login(client, email="forgot-fail@zerostrike.dev", password="oldpassword1")

    def broken(*args, **kwargs):
        raise ConnectionRefusedError("smtp down")

    monkeypatch.setattr(email_service, "send_password_reset_email", broken)
    r = client.post("/api/v1/auth/forgot-password", json={"email": "forgot-fail@zerostrike.dev"})

    assert r.status_code == 200
    assert r.json()["message"] == "If that email is registered, a reset link has been sent."
    failed = asyncio.run(AuditLog.find(AuditLog.action == "Password Reset Email Failed").to_list())
    assert len(failed) == 1
    assert failed[0].actor_type == "system"
    assert failed[0].metadata == {"error": "ConnectionRefusedError"}
    notes = client.get("/api/v1/notifications", headers=admin).json()["items"]
    assert any(n["event"] == "email.delivery_failed" for n in notes)


def test_known_email_send_is_deferred_until_after_response(client, monkeypatch):
    from fastapi import BackgroundTasks

    from app.services import auth_service

    captured = {}
    _capture_send(monkeypatch, captured)
    register_and_login(client, email="forgot-defer@zerostrike.dev", password="oldpassword1")

    async def run():
        bg = BackgroundTasks()
        await auth_service.request_password_reset("forgot-defer@zerostrike.dev", bg)
        before = dict(captured)
        scheduled = len(bg.tasks)
        await bg()
        return before, scheduled

    before, scheduled = asyncio.run(run())
    assert before == {}
    assert scheduled == 1
    assert captured["to_address"] == "forgot-defer@zerostrike.dev"


def test_unknown_email_schedules_nothing(client, monkeypatch):
    from fastapi import BackgroundTasks

    from app.services import auth_service

    captured = {}
    _capture_send(monkeypatch, captured)

    async def run():
        bg = BackgroundTasks()
        await auth_service.request_password_reset("nobody-defer@zerostrike.dev", bg)
        return len(bg.tasks)

    assert asyncio.run(run()) == 0
    assert captured == {}

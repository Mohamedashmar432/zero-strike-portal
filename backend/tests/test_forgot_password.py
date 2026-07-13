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

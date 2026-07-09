import asyncio
from datetime import datetime, timedelta, timezone

from app.models.api_key import ApiKey
from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _create_key(client, headers, project_id, label="scanner", days=30):
    r = client.post(
        "/api/v1/apikeys",
        json={"project_id": project_id, "label": label, "expires_in_days": days},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


def test_create_key_returns_raw_token_once_only(client):
    owner = register_and_login(client, email="kowner1@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    key = _create_key(client, _headers(owner), project["id"])
    assert key["raw_token"].startswith("zst_live_")

    r = client.get(f"/api/v1/apikeys/{key['id']}", headers=_headers(owner))
    assert "raw_token" not in r.json()
    assert "key_hash" not in r.json()


def test_non_member_cannot_create_key(client):
    owner = register_and_login(client, email="kowner2@zerostrike.dev")
    outsider = register_and_login(client, email="koutsider2@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    r = client.post(
        "/api/v1/apikeys",
        json={"project_id": project["id"], "label": "x", "expires_in_days": 30},
        headers=_headers(outsider),
    )
    assert r.status_code == 403


def test_validate_succeeds_and_updates_last_used(client):
    owner = register_and_login(client, email="kowner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    key = _create_key(client, _headers(owner), project["id"])

    r = client.post("/api/v1/apikeys/validate", json={"token": key["raw_token"]})
    assert r.status_code == 200
    assert r.json()["project_id"] == project["id"]

    detail = client.get(f"/api/v1/apikeys/{key['id']}", headers=_headers(owner)).json()
    assert detail["last_used_at"] is not None


def test_revoked_key_fails_validation_with_generic_401(client):
    owner = register_and_login(client, email="kowner4@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    key = _create_key(client, _headers(owner), project["id"])

    r = client.delete(f"/api/v1/apikeys/{key['id']}", headers=_headers(owner))
    assert r.status_code == 204

    r = client.post("/api/v1/apikeys/validate", json={"token": key["raw_token"]})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired API key"


def test_expired_key_fails_validation(client):
    owner = register_and_login(client, email="kowner5@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    key = _create_key(client, _headers(owner), project["id"])

    async def expire_it():
        k = await ApiKey.get(key["id"])
        k.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await k.save()

    asyncio.run(expire_it())

    r = client.post("/api/v1/apikeys/validate", json={"token": key["raw_token"]})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired API key"


def test_unknown_token_gets_same_generic_401(client):
    r = client.post("/api/v1/apikeys/validate", json={"token": "zst_live_garbage"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired API key"


def test_revoke_is_idempotent(client):
    owner = register_and_login(client, email="kowner6@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    key = _create_key(client, _headers(owner), project["id"])

    assert client.delete(f"/api/v1/apikeys/{key['id']}", headers=_headers(owner)).status_code == 204
    assert client.delete(f"/api/v1/apikeys/{key['id']}", headers=_headers(owner)).status_code == 204

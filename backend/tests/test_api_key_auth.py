import asyncio
from datetime import datetime, timedelta, timezone

from app.models.api_key import ApiKey
from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _project(client, headers, name="Demo"):
    return client.post("/api/v1/projects", json={"name": name}, headers=headers).json()


def _raw_key(client, headers, project_id):
    r = client.post(
        "/api/v1/apikeys",
        json={"project_id": project_id, "label": "scanner", "expires_in_days": 30},
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


def _scanner_headers(raw_token):
    return {"Authorization": f"Bearer {raw_token}"}


def test_valid_api_key_authorizes_scanner_call_and_updates_last_used(client):
    owner = register_and_login(client, email="akowner1@zerostrike.dev")
    project = _project(client, _headers(owner))
    key = _raw_key(client, _headers(owner), project["id"])

    r = client.post(
        "/api/v1/scans",
        json={"project_id": project["id"], "scanner_version": "v0.22.0"},
        headers=_scanner_headers(key["raw_token"]),
    )
    assert r.status_code == 201

    detail = client.get(f"/api/v1/apikeys/{key['id']}", headers=_headers(owner)).json()
    assert detail["last_used_at"] is not None


def test_unknown_token_rejected_401(client):
    owner = register_and_login(client, email="akowner2@zerostrike.dev")
    project = _project(client, _headers(owner))
    r = client.post(
        "/api/v1/scans",
        json={"project_id": project["id"], "scanner_version": "v0.22.0"},
        headers=_scanner_headers("zst_live_not_a_real_token"),
    )
    assert r.status_code == 401


def test_revoked_key_rejected_401(client):
    owner = register_and_login(client, email="akowner3@zerostrike.dev")
    project = _project(client, _headers(owner))
    key = _raw_key(client, _headers(owner), project["id"])
    assert client.delete(f"/api/v1/apikeys/{key['id']}", headers=_headers(owner)).status_code == 204

    r = client.post(
        "/api/v1/scans",
        json={"project_id": project["id"], "scanner_version": "v0.22.0"},
        headers=_scanner_headers(key["raw_token"]),
    )
    assert r.status_code == 401


def test_expired_key_rejected_401(client):
    owner = register_and_login(client, email="akowner4@zerostrike.dev")
    project = _project(client, _headers(owner))
    key = _raw_key(client, _headers(owner), project["id"])

    async def expire():
        k = await ApiKey.get(key["id"])
        k.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        await k.save()

    asyncio.run(expire())

    r = client.post(
        "/api/v1/scans",
        json={"project_id": project["id"], "scanner_version": "v0.22.0"},
        headers=_scanner_headers(key["raw_token"]),
    )
    assert r.status_code == 401

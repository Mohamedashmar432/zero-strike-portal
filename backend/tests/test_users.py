import asyncio

from app.models.user import User
from tests.test_auth_flow import register_and_login


def _promote_to_admin(email: str) -> None:
    async def _promote():
        user = await User.find_one(User.email == email)
        user.role = "admin"
        await user.save()

    asyncio.run(_promote())


def _admin_headers(client, email="admin@zerostrike.dev"):
    register_and_login(client, email=email)
    _promote_to_admin(email)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "hunter2pass"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_update_my_profile_changes_name(client):
    tokens = register_and_login(client, email="profile@zerostrike.dev")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.patch("/api/v1/users/me", json={"name": "New Name"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "New Name"

    r = client.get("/api/v1/users/me", headers=headers)
    assert r.json()["name"] == "New Name"


def test_update_my_profile_partial_update_is_noop_when_omitted(client):
    tokens = register_and_login(client, email="noop@zerostrike.dev")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}

    r = client.patch("/api/v1/users/me", json={}, headers=headers)
    assert r.status_code == 200
    assert r.json()["name"] == "User"


def test_non_admin_forbidden_on_admin_user_routes(client):
    tokens = register_and_login(client, email="plain@zerostrike.dev")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    other = register_and_login(client, email="other@zerostrike.dev")
    other_id = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {other['access_token']}"}).json()["id"]

    assert client.get("/api/v1/users", headers=headers).status_code == 403
    assert client.get(f"/api/v1/users/{other_id}", headers=headers).status_code == 403
    assert client.patch(f"/api/v1/users/{other_id}", json={"role": "admin"}, headers=headers).status_code == 403
    assert client.delete(f"/api/v1/users/{other_id}", headers=headers).status_code == 403


def test_admin_can_list_users_paginated(client):
    register_and_login(client, email="u1@zerostrike.dev")
    register_and_login(client, email="u2@zerostrike.dev")
    headers = _admin_headers(client)

    r = client.get("/api/v1/users?page=1&page_size=20", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 3
    assert body["page"] == 1
    assert body["page_size"] == 20


def test_admin_get_user_by_id(client):
    tokens = register_and_login(client, email="target@zerostrike.dev")
    headers = _admin_headers(client)
    user_id = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()["id"]

    assert client.get(f"/api/v1/users/{user_id}", headers=headers).status_code == 200
    assert client.get("/api/v1/users/000000000000000000000000", headers=headers).status_code == 404


def test_admin_update_user_role_and_active(client):
    tokens = register_and_login(client, email="demote@zerostrike.dev")
    user_headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    admin_headers = _admin_headers(client)
    user_id = client.get("/api/v1/users/me", headers=user_headers).json()["id"]

    r = client.patch(f"/api/v1/users/{user_id}", json={"is_active": False}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    # Deactivation must invalidate the still-unexpired access token on the next call.
    r = client.get("/api/v1/users/me", headers=user_headers)
    assert r.status_code == 401


def test_admin_delete_user(client):
    tokens = register_and_login(client, email="deleteme@zerostrike.dev")
    admin_headers = _admin_headers(client)
    user_id = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    ).json()["id"]

    assert client.delete(f"/api/v1/users/{user_id}", headers=admin_headers).status_code == 204
    assert client.get(f"/api/v1/users/{user_id}", headers=admin_headers).status_code == 404

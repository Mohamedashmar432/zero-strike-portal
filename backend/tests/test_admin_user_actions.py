from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def test_admin_cannot_update_own_account_via_admin_endpoint(client):
    admin_headers = _admin_headers(client, email="selfmod-admin1@zerostrike.dev")
    admin_id = client.get("/api/v1/users/me", headers=admin_headers).json()["id"]

    r = client.patch(f"/api/v1/users/{admin_id}", json={"role": "user"}, headers=admin_headers)
    assert r.status_code == 400

    # Guard fires before mutation — role must be untouched.
    r = client.get(f"/api/v1/users/{admin_id}", headers=admin_headers)
    assert r.json()["role"] == "admin"


def test_admin_cannot_delete_own_account_via_admin_endpoint(client):
    admin_headers = _admin_headers(client, email="selfmod-admin2@zerostrike.dev")
    admin_id = client.get("/api/v1/users/me", headers=admin_headers).json()["id"]

    r = client.delete(f"/api/v1/users/{admin_id}", headers=admin_headers)
    assert r.status_code == 400

    r = client.get(f"/api/v1/users/{admin_id}", headers=admin_headers)
    assert r.status_code == 200


def test_admin_can_still_modify_a_different_admin_account(client):
    admin_headers = _admin_headers(client, email="selfmod-admin3@zerostrike.dev")
    other_tokens = register_and_login(client, email="selfmod-other3@zerostrike.dev")
    other_id = client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {other_tokens['access_token']}"}
    ).json()["id"]

    # Promote the other user to admin — the self-modification guard must not block acting on
    # someone else, even once that someone-else is also an admin.
    r = client.patch(f"/api/v1/users/{other_id}", json={"role": "admin"}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"

    r = client.delete(f"/api/v1/users/{other_id}", headers=admin_headers)
    assert r.status_code == 204

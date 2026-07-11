from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_wrong_current_password_rejected_and_password_unchanged(client):
    tokens = register_and_login(client, email="cp1@zerostrike.dev", password="correctpass1")
    headers = _headers(tokens)

    r = client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "wrongpass1", "new_password": "newpassword1"},
        headers=headers,
    )
    assert r.status_code == 400

    # Nothing was mutated — the original password still works.
    r = client.post("/api/v1/auth/login", json={"email": "cp1@zerostrike.dev", "password": "correctpass1"})
    assert r.status_code == 200


def test_change_password_success_flips_which_password_works(client):
    tokens = register_and_login(client, email="cp2@zerostrike.dev", password="correctpass1")
    headers = _headers(tokens)

    r = client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "correctpass1", "new_password": "newpassword1"},
        headers=headers,
    )
    assert r.status_code == 204

    r = client.post("/api/v1/auth/login", json={"email": "cp2@zerostrike.dev", "password": "correctpass1"})
    assert r.status_code == 401

    r = client.post("/api/v1/auth/login", json={"email": "cp2@zerostrike.dev", "password": "newpassword1"})
    assert r.status_code == 200


def test_change_password_revokes_existing_refresh_token(client):
    tokens = register_and_login(client, email="cp3@zerostrike.dev", password="correctpass1")
    headers = _headers(tokens)
    old_refresh_token = tokens["refresh_token"]

    r = client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "correctpass1", "new_password": "newpassword1"},
        headers=headers,
    )
    assert r.status_code == 204

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh_token})
    assert r.status_code == 401


def test_change_password_requires_auth(client):
    r = client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "whatever1", "new_password": "newpassword1"},
    )
    assert r.status_code in (401, 403)


def test_change_password_rejects_short_new_password(client):
    tokens = register_and_login(client, email="cp4@zerostrike.dev", password="correctpass1")
    headers = _headers(tokens)

    r = client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "correctpass1", "new_password": "short"},
        headers=headers,
    )
    assert r.status_code == 422

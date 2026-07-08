def register_and_login(client, email="user@zerostrike.dev", password="hunter2pass"):
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password, "name": "User"})
    assert r.status_code == 201
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return r.json()


def test_register_login_me(client):
    tokens = register_and_login(client)
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200
    assert r.json()["role"] == "user"


def test_non_admin_cannot_list_users(client):
    tokens = register_and_login(client)
    r = client.get("/api/v1/users", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 403


def test_refresh_rotates_and_detects_reuse(client):
    tokens = register_and_login(client)
    old_refresh = tokens["refresh_token"]

    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["refresh_token"] != old_refresh

    # Reusing the rotated-out token is treated as theft.
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert r.status_code == 401

    # Theft detection revokes the entire chain, including the latest token.
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]})
    assert r.status_code == 401


def test_logout_revokes_refresh_token(client):
    tokens = register_and_login(client)
    r = client.post("/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 204
    r = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 401

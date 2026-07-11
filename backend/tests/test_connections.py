import asyncio
from urllib.parse import parse_qs, urlparse

from app.core import security
from app.models.oauth_connection import OAuthConnection
from app.services.oauth import OAuthProviderError, github
from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _me(client, tokens):
    return client.get("/api/v1/auth/me", headers=_headers(tokens)).json()


def _state_from_authorize_url(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


async def _fake_exchange_code(code):
    return {"access_token": f"gho_{code}", "scope": "repo"}


async def _fake_fetch_identity(access_token):
    return {"external_account_id": "12345", "account_login": "octocat"}


def test_encrypt_decrypt_round_trip():
    encrypted = security.encrypt_secret("super-secret-value")
    assert encrypted != "super-secret-value"
    assert security.decrypt_secret(encrypted) == "super-secret-value"


def test_authorize_returns_url_and_sets_state_cookie(client):
    owner = register_and_login(client, email="oauth1@zerostrike.dev")
    r = client.post("/api/v1/connections/github/authorize", headers=_headers(owner))
    assert r.status_code == 200
    assert "github.com/login/oauth/authorize" in r.json()["authorize_url"]
    assert "zs_oauth_state" in r.cookies


def test_authorize_requires_auth(client):
    r = client.post("/api/v1/connections/github/authorize")
    assert r.status_code == 403 or r.status_code == 401


def test_unknown_provider_404s(client):
    owner = register_and_login(client, email="oauth2@zerostrike.dev")
    r = client.post("/api/v1/connections/gitlab/authorize", headers=_headers(owner))
    assert r.status_code == 404


def test_callback_upserts_connection_and_lists_it(client, monkeypatch):
    monkeypatch.setattr(github, "exchange_code", _fake_exchange_code)
    monkeypatch.setattr(github, "fetch_identity", _fake_fetch_identity)

    owner = register_and_login(client, email="oauth3@zerostrike.dev")
    me = _me(client, owner)
    authorize_url = client.post("/api/v1/connections/github/authorize", headers=_headers(owner)).json()[
        "authorize_url"
    ]
    state = _state_from_authorize_url(authorize_url)

    r = client.get(f"/api/v1/connections/github/callback?code=abc123&state={state}", follow_redirects=False)
    assert r.status_code == 302
    assert "connected=github" in r.headers["location"]

    async def _check():
        conn = await OAuthConnection.find_one(
            OAuthConnection.user_id == me["id"], OAuthConnection.provider == "github"
        )
        assert conn is not None
        assert conn.account_login == "octocat"
        assert conn.access_token_encrypted != "gho_abc123"  # never stored in plaintext
        assert security.decrypt_secret(conn.access_token_encrypted) == "gho_abc123"

    asyncio.run(_check())

    r = client.get("/api/v1/connections", headers=_headers(owner))
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["account_login"] == "octocat"
    assert "access_token_encrypted" not in body[0]


def test_callback_rejects_mismatched_session_cookie(client, monkeypatch):
    monkeypatch.setattr(github, "exchange_code", _fake_exchange_code)
    monkeypatch.setattr(github, "fetch_identity", _fake_fetch_identity)

    owner = register_and_login(client, email="oauth4@zerostrike.dev")
    authorize_url = client.post("/api/v1/connections/github/authorize", headers=_headers(owner)).json()[
        "authorize_url"
    ]
    state = _state_from_authorize_url(authorize_url)

    # Simulate a different browser completing the callback (e.g. an attacker's authorize_url sent
    # to a victim) — the session-binding cookie won't match the state's jti.
    r = client.get(
        f"/api/v1/connections/github/callback?code=abc123&state={state}",
        cookies={"zs_oauth_state": "not-the-right-jti"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    assert "error=oauth_failed" in r.headers["location"]

    async def _check_none():
        assert await OAuthConnection.find_one(OAuthConnection.provider == "github") is None

    asyncio.run(_check_none())


def test_disconnect_removes_connection(client, monkeypatch):
    monkeypatch.setattr(github, "exchange_code", _fake_exchange_code)
    monkeypatch.setattr(github, "fetch_identity", _fake_fetch_identity)

    owner = register_and_login(client, email="oauth5@zerostrike.dev")
    authorize_url = client.post("/api/v1/connections/github/authorize", headers=_headers(owner)).json()[
        "authorize_url"
    ]
    state = _state_from_authorize_url(authorize_url)
    client.get(f"/api/v1/connections/github/callback?code=abc123&state={state}", follow_redirects=False)

    r = client.delete("/api/v1/connections/github", headers=_headers(owner))
    assert r.status_code == 204
    assert client.get("/api/v1/connections", headers=_headers(owner)).json() == []

    r = client.delete("/api/v1/connections/github", headers=_headers(owner))
    assert r.status_code == 404


def test_github_repos_uses_connection(client, monkeypatch):
    monkeypatch.setattr(github, "exchange_code", _fake_exchange_code)
    monkeypatch.setattr(github, "fetch_identity", _fake_fetch_identity)

    async def _fake_list_repos(access_token, query, page):
        assert access_token == "gho_abc123"
        return [
            {
                "id": "1",
                "name": "repo",
                "full_name": "octocat/repo",
                "clone_url": "https://github.com/octocat/repo.git",
                "private": False,
                "default_branch": "main",
            }
        ]

    monkeypatch.setattr(github, "list_repos", _fake_list_repos)

    owner = register_and_login(client, email="oauth6@zerostrike.dev")
    authorize_url = client.post("/api/v1/connections/github/authorize", headers=_headers(owner)).json()[
        "authorize_url"
    ]
    state = _state_from_authorize_url(authorize_url)
    client.get(f"/api/v1/connections/github/callback?code=abc123&state={state}", follow_redirects=False)

    r = client.get("/api/v1/connections/github/repos", headers=_headers(owner))
    assert r.status_code == 200
    assert r.json() == [
        {
            "id": "1",
            "name": "repo",
            "full_name": "octocat/repo",
            "clone_url": "https://github.com/octocat/repo.git",
            "private": False,
            "default_branch": "main",
        }
    ]


def test_github_repos_without_connection_404s(client):
    owner = register_and_login(client, email="oauth7@zerostrike.dev")
    r = client.get("/api/v1/connections/github/repos", headers=_headers(owner))
    assert r.status_code == 404


def test_github_repos_upstream_failure_is_502_not_500(client, monkeypatch):
    """A revoked/expired token or provider outage must surface as a clean 502, not an unhandled
    500 — regression test for OAuthProviderError previously escaping unhandled to the ASGI layer."""
    monkeypatch.setattr(github, "exchange_code", _fake_exchange_code)
    monkeypatch.setattr(github, "fetch_identity", _fake_fetch_identity)

    async def _fake_list_repos_fails(access_token, query, page):
        raise OAuthProviderError("GitHub repo listing failed")

    monkeypatch.setattr(github, "list_repos", _fake_list_repos_fails)

    owner = register_and_login(client, email="oauth11@zerostrike.dev")
    authorize_url = client.post("/api/v1/connections/github/authorize", headers=_headers(owner)).json()[
        "authorize_url"
    ]
    state = _state_from_authorize_url(authorize_url)
    client.get(f"/api/v1/connections/github/callback?code=abc123&state={state}", follow_redirects=False)

    r = client.get("/api/v1/connections/github/repos", headers=_headers(owner))
    assert r.status_code == 502


def test_create_cloud_scan_via_connection_id(client, monkeypatch):
    import app.services.scan_queue_service as scan_queue_service

    async def _noop(*args, **kwargs):
        pass

    monkeypatch.setattr(scan_queue_service, "drain_queue", _noop)
    monkeypatch.setattr(github, "exchange_code", _fake_exchange_code)
    monkeypatch.setattr(github, "fetch_identity", _fake_fetch_identity)

    owner = register_and_login(client, email="oauth8@zerostrike.dev")
    authorize_url = client.post("/api/v1/connections/github/authorize", headers=_headers(owner)).json()[
        "authorize_url"
    ]
    state = _state_from_authorize_url(authorize_url)
    client.get(f"/api/v1/connections/github/callback?code=abc123&state={state}", follow_redirects=False)
    connection_id = client.get("/api/v1/connections", headers=_headers(owner)).json()[0]["id"]

    project = client.post("/api/v1/projects", json={"name": "Imported"}, headers=_headers(owner)).json()
    r = client.post(
        f"/api/v1/projects/{project['id']}/scans",
        json={"scan_type": "cloud", "repo_url": "https://github.com/octocat/repo", "connection_id": connection_id},
        headers=_headers(owner),
    )
    assert r.status_code == 201

    async def _check_token():
        from app.models.scan import Scan

        scan = await Scan.get(r.json()["id"])
        assert scan.repo_token == "gho_abc123"

    asyncio.run(_check_token())


def test_create_cloud_scan_rejects_both_token_and_connection(client):
    owner = register_and_login(client, email="oauth9@zerostrike.dev")
    project = client.post("/api/v1/projects", json={"name": "Bad"}, headers=_headers(owner)).json()
    r = client.post(
        f"/api/v1/projects/{project['id']}/scans",
        json={
            "scan_type": "cloud",
            "repo_url": "https://github.com/octocat/repo",
            "repo_token": "manual-token",
            "connection_id": "someid",
        },
        headers=_headers(owner),
    )
    assert r.status_code == 422


def test_connection_id_from_other_user_is_rejected(client, monkeypatch):
    monkeypatch.setattr(github, "exchange_code", _fake_exchange_code)
    monkeypatch.setattr(github, "fetch_identity", _fake_fetch_identity)

    owner_a = register_and_login(client, email="oauth10a@zerostrike.dev")
    authorize_url = client.post("/api/v1/connections/github/authorize", headers=_headers(owner_a)).json()[
        "authorize_url"
    ]
    state = _state_from_authorize_url(authorize_url)
    client.get(f"/api/v1/connections/github/callback?code=abc123&state={state}", follow_redirects=False)
    connection_id = client.get("/api/v1/connections", headers=_headers(owner_a)).json()[0]["id"]

    owner_b = register_and_login(client, email="oauth10b@zerostrike.dev")
    project = client.post("/api/v1/projects", json={"name": "NotYours"}, headers=_headers(owner_b)).json()
    r = client.post(
        f"/api/v1/projects/{project['id']}/scans",
        json={"scan_type": "cloud", "repo_url": "https://github.com/octocat/repo", "connection_id": connection_id},
        headers=_headers(owner_b),
    )
    assert r.status_code == 404

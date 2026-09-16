"""Covers app-level wiring that no router-specific test file exercises: the /health
check and the request-id middleware added in the architecture-hardening pass.
"""

import app.main as main_module
import app.services.cloud_scan_service as cloud_scan_service


def test_health_reports_ok_when_mongo_and_scanner_are_up(client, monkeypatch):
    monkeypatch.setattr(cloud_scan_service, "scanner_available", lambda: True)
    resp = client.get("/health")
    assert resp.status_code == 200
    # Exact shape on purpose -- /health is a contract other things poll. scanner_build says WHICH
    # engine is baked in, which "scanner": True cannot (a ten-releases-old binary is present too).
    assert resp.json() == {
        "status": "ok",
        "mongo": True,
        "scanner": True,
        "scanner_build": "unknown",  # not stamped outside a Docker build
    }


def test_health_returns_503_when_mongo_ping_fails(client, monkeypatch):
    class _BrokenDB:
        async def command(self, *_args, **_kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr(main_module, "get_database", lambda: _BrokenDB())
    monkeypatch.setattr(cloud_scan_service, "scanner_available", lambda: True)

    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["mongo"] is False
    assert body["scanner"] is True


def test_health_returns_503_when_scanner_binary_missing(client, monkeypatch):
    monkeypatch.setattr(cloud_scan_service, "scanner_available", lambda: False)
    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["mongo"] is True
    assert body["scanner"] is False


def test_response_echoes_inbound_request_id(client):
    resp = client.get("/health", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["x-request-id"] == "abc-123"


def test_response_generates_request_id_when_absent(client):
    r1 = client.get("/health")
    r2 = client.get("/health")
    assert r1.headers["x-request-id"]
    assert r2.headers["x-request-id"]
    assert r1.headers["x-request-id"] != r2.headers["x-request-id"]


# --- Malformed ObjectIds ------------------------------------------------------------------
# Beanie's Document.get() RAISES on an id that isn't a valid ObjectId rather than returning
# None, so before the InvalidId handler every hand-typed, truncated or stale URL surfaced as a
# raw 500: an unhandled crash in the logs and a plain-text body that breaks a .json() parse.
# Found by an adversarial QA pass, not by the feature suites — no UI ever types a bad id.


def _auth(client):
    from tests.test_auth_flow import register_and_login

    tokens = register_and_login(client, email="bad-id-probe@zerostrike.dev")
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_malformed_object_id_is_404_not_500(client):
    headers = _auth(client)
    real = client.post("/api/v1/projects", json={"name": "P"}, headers=headers).json()["id"]

    for path in (
        "/api/v1/projects/not-an-id",
        "/api/v1/scans/not-an-id",
        "/api/v1/projects/not-an-id/vulnerabilities",
        f"/api/v1/projects/{real}/vulnerabilities/not-an-id",
        f"/api/v1/projects/{real}/scans/not-an-id/regression",
        "/api/v1/projects/not-an-id/audit-log",
    ):
        resp = client.get(path, headers=headers)
        assert resp.status_code != 500, f"{path} crashed instead of 404"
        assert resp.status_code in (403, 404), f"{path} -> {resp.status_code}"
        # Must stay JSON: a plain-text 500 body is what broke the client's .json() parse.
        assert "detail" in resp.json()


def test_malformed_object_id_on_a_write_is_404_not_500(client):
    headers = _auth(client)
    real = client.post("/api/v1/projects", json={"name": "P2"}, headers=headers).json()["id"]

    resp = client.patch(
        f"/api/v1/projects/{real}/vulnerabilities/not-an-id/status",
        json={"status": "in_progress"},
        headers=headers,
    )
    assert resp.status_code == 404
    assert "detail" in resp.json()

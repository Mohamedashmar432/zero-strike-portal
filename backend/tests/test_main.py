"""Covers app-level wiring that no router-specific test file exercises: the /health
check and the request-id middleware added in the architecture-hardening pass.
"""

import app.main as main_module
import app.services.cloud_scan_service as cloud_scan_service


def test_health_reports_ok_when_mongo_and_scanner_are_up(client, monkeypatch):
    monkeypatch.setattr(cloud_scan_service, "scanner_available", lambda: True)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "mongo": True, "scanner": True}


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

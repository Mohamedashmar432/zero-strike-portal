from types import SimpleNamespace

from app.core.config import settings
from app.core.rate_limit import client_ip


def _req(xff=None, peer="10.0.0.5"):
    headers = {"x-forwarded-for": xff} if xff is not None else {}
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=peer))


def test_client_ip_takes_rightmost_trusted_hop(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    assert client_ip(_req("1.1.1.1, 203.0.113.9")) == "203.0.113.9"


def test_client_ip_two_hops(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    assert client_ip(_req("6.6.6.6, 1.1.1.1, 203.0.113.9")) == "1.1.1.1"


def test_client_ip_zero_hops_ignores_header(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 0)
    assert client_ip(_req("1.1.1.1, 203.0.113.9")) == "10.0.0.5"


def test_client_ip_short_header_falls_back_to_peer(monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 2)
    assert client_ip(_req("1.1.1.1")) == "10.0.0.5"
    assert client_ip(_req()) == "10.0.0.5"


def test_login_account_bucket_holds_across_rotating_forwarded_for(client, monkeypatch):
    monkeypatch.setattr(settings, "trusted_proxy_hops", 1)
    statuses = []
    for i in range(21):
        r = client.post(
            "/api/v1/auth/login",
            json={"email": "Victim@zerostrike.dev", "password": "wrong-password"},
            headers={"X-Forwarded-For": f"198.51.100.{i}"},
        )
        statuses.append(r.status_code)
    assert 429 not in statuses[:20]
    assert statuses[20] == 429


def test_register_rejects_password_over_72_bytes(client):
    def reg(pw, email):
        return client.post("/api/v1/auth/register", json={"email": email, "password": pw, "name": "U"})

    assert reg("a" * 73, "long@zerostrike.dev").status_code == 422
    assert reg("é" * 37, "multi@zerostrike.dev").status_code == 422  # 74 bytes
    assert reg("a" * 72, "ok@zerostrike.dev").status_code == 201

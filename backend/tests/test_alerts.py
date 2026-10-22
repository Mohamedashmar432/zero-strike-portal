"""Alert channels: owner-only config, secret webhook never echoed, SSRF refusal, trigger gating."""

import asyncio
from types import SimpleNamespace

from app.services import alert_service
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

HOOK = "https://example.webhook.office.com/webhookb2/secret-token-123"


def _h(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _project(client, h):
    return client.post("/api/v1/projects", json={"name": "Alert Demo"}, headers=h).json()["id"]


def _allow_dns(monkeypatch):
    monkeypatch.setattr(alert_service, "resolve_vetted_ips", lambda host: ["93.184.216.34"])


def test_owner_configures_and_url_is_never_returned(client, monkeypatch):
    _allow_dns(monkeypatch)
    h = _h(register_and_login(client, email="al-owner@zs.dev"))
    pid = _project(client, h)
    r = client.put(
        f"/api/v1/projects/{pid}/alerts",
        json={"webhook_url": HOOK, "webhook_enabled": True, "emails": ["a@x.io", "A@x.io", "b@x.io"]},
        headers=h,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["webhook_host"] == "example.webhook.office.com"
    assert "secret-token" not in r.text
    assert body["emails"] == ["a@x.io", "b@x.io"]  # case-insensitive de-dupe


def test_more_than_three_emails_and_private_hosts_are_refused(client, monkeypatch):
    h = _h(register_and_login(client, email="al-limits@zs.dev"))
    pid = _project(client, h)
    four = [f"u{i}@x.io" for i in range(4)]
    assert client.put(f"/api/v1/projects/{pid}/alerts", json={"emails": four}, headers=h).status_code == 422
    # real resolver: loopback is not globally routable
    r = client.put(f"/api/v1/projects/{pid}/alerts", json={"webhook_url": "https://localhost/x"}, headers=h)
    assert r.status_code == 422
    r = client.put(f"/api/v1/projects/{pid}/alerts", json={"webhook_url": "http://example.com/x"}, headers=h)
    assert r.status_code == 422


def test_non_owner_cannot_read_or_write(client):
    owner = _h(register_and_login(client, email="al-o2@zs.dev"))
    other = _h(register_and_login(client, email="al-other@zs.dev"))
    pid = _project(client, owner)
    assert client.get(f"/api/v1/projects/{pid}/alerts", headers=other).status_code in (403, 404)
    assert client.put(f"/api/v1/projects/{pid}/alerts", json={}, headers=other).status_code in (403, 404)


def test_global_webhook_is_admin_only(client, monkeypatch):
    _allow_dns(monkeypatch)
    user = _h(register_and_login(client, email="al-plain@zs.dev"))
    assert client.get("/api/v1/workspace-settings/alerts", headers=user).status_code == 403
    admin = _admin_headers(client, email="al-admin@zs.dev")
    r = client.put(
        "/api/v1/workspace-settings/alerts", json={"webhook_url": HOOK, "webhook_enabled": True}, headers=admin
    )
    assert r.status_code == 200 and r.json()["webhook_configured"] is True
    assert "secret-token" not in r.text


def test_triggers_gate_what_fires(monkeypatch):
    sent = []

    async def fake(enc, title, text, link, project_id, meta, facts=None):
        sent.append(title)

    monkeypatch.setattr(alert_service, "_safe_webhook", fake)
    project = SimpleNamespace(
        id="p1",
        name="P",
        alert_triggers=["critical"],
        alert_webhook_enabled=True,
        alert_webhook_enc="x",
        alert_email_enabled=False,
        alert_emails=[],
    )

    async def run():
        await alert_service.send_project_alert(project, "high", "t", "b", None)  # off -> silent
        await alert_service.send_project_alert(project, "critical", "t", "b", None)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert sent == ["t"]


def test_scan_completion_emails_the_pdf_and_audits_it(client, monkeypatch):
    import time
    from pathlib import Path

    from app.models.audit_log import AuditLog
    from tests.test_pdf_report import _create_scan

    sent = []
    monkeypatch.setattr(
        alert_service.email_service,
        "send_email",
        lambda to, subject, text, html=None, attachments=None: to == "a@x.io" and sent.append((to, text, attachments)),
    )
    h = _h(register_and_login(client, email="al-e2e@zs.dev"))
    pid = _project(client, h)
    r = client.put(
        f"/api/v1/projects/{pid}/alerts", json={"emails": ["a@x.io"], "email_enabled": True}, headers=h
    )
    assert r.status_code == 200
    fixture = Path(__file__).parent / "fixtures" / "go_report_sample.json"
    _create_scan(client, h, pid, report_bytes=fixture.read_bytes())

    for _ in range(50):
        if sent:
            break
        time.sleep(0.1)
    assert sent, "no alert email was sent"
    to, text, attachments = sent[0]
    assert to == "a@x.io"
    # The link carries the alert marker so a signed-out visitor is routed to register/sign-in.
    assert f"/projects/{pid}/scans/" in text and "src=alert" in text
    # Repo, branch and per-severity counts are in the body, not only the PDF.
    assert all(k in text for k in ("Repository:", "Branch:", "Critical:", "High:", "Medium:", "Low:"))
    name, data = attachments[0]
    assert name.endswith(".pdf") and data.startswith(b"%PDF")


    async def rows():
        return await AuditLog.find(AuditLog.project_id == pid, AuditLog.action == "Alert Sent").to_list()

    for _ in range(50):
        found = asyncio.run(rows())
        if found:
            break
        time.sleep(0.1)
    assert found, "delivery was not audited"
    # A background delivery is not a person's action, and the row must not carry an address.
    assert found[0].actor_type == "system"
    assert found[0].metadata["channel"] == "email" and found[0].metadata["pdf_attached"] is True
    assert "a@x.io" not in str(found[0].metadata)

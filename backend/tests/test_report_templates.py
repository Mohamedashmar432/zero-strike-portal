from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_preview_returns_html_for_both_templates(client):
    for template in ("standard", "executive"):
        r = client.get(f"/api/v1/report-templates/{template}/preview")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "Sample Project" in r.text
        assert "SQL Injection" in r.text


def test_get_default_report_template_settings(client):
    r = client.get("/api/v1/report-templates/settings")
    assert r.status_code == 200
    assert r.json()["default_report_template"] == "standard"


def test_only_admin_can_update_default_report_template(client):
    owner = register_and_login(client, email="rt-owner@zerostrike.dev")
    r = client.put(
        "/api/v1/report-templates/settings",
        json={"default_report_template": "executive"},
        headers=_headers(owner),
    )
    assert r.status_code == 403

    admin_headers = _admin_headers(client, email="rt-admin@zerostrike.dev")
    r = client.put(
        "/api/v1/report-templates/settings",
        json={"default_report_template": "executive"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["default_report_template"] == "executive"

    r = client.get("/api/v1/report-templates/settings")
    assert r.json()["default_report_template"] == "executive"

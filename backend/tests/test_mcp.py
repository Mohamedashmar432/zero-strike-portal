"""Admin MCP server (docs/ADMIN_MCP.md): token lifecycle, the auth wrapper, and every tool over
the real mounted /mcp endpoint."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.mcp import server as mcp_server
from app.models.audit_log import AuditLog
from app.models.mcp_token import McpToken
from app.models.system_log import SystemLog
from app.models.user import User
from tests.test_auth_flow import register_and_login
from tests.test_users import _promote_to_admin

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _admin(client, email="mcpadmin@zerostrike.dev"):
    register_and_login(client, email=email)
    _promote_to_admin(email)
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "hunter2pass"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _issue(client, headers, label="dev laptop", days=30):
    r = client.post("/api/v1/admin/mcp-tokens", json={"label": label, "expires_in_days": days}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _rpc(client, token, method, params=None, id_=1):
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}, headers=headers)


def _call(client, token, tool, **arguments):
    r = _rpc(client, token, "tools/call", {"name": tool, "arguments": arguments})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert not result.get("isError"), result
    return result["structuredContent"] if result.get("structuredContent") else json.loads(result["content"][0]["text"])


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def admin_token(client):
    headers = _admin(client)
    return headers, _issue(client, headers)["raw_token"]


# --- tokens -----------------------------------------------------------------


def test_issue_returns_raw_token_once_and_stores_only_a_hash(client):
    headers = _admin(client)
    issued = _issue(client, headers)
    assert issued["raw_token"].startswith("tsmcp_")
    listed = client.get("/api/v1/admin/mcp-tokens", headers=headers).json()
    assert [t["id"] for t in listed] == [issued["id"]]
    assert "raw_token" not in listed[0] and "key_hash" not in listed[0]
    stored = _run(McpToken.find_all().to_list())[0]
    assert issued["raw_token"] not in stored.key_hash
    assert stored.expires_at - stored.created_at <= timedelta(days=90, seconds=5)


def test_expiry_is_limited_to_the_offered_choices(client):
    headers = _admin(client)
    r = client.post("/api/v1/admin/mcp-tokens", json={"label": "x", "expires_in_days": 365}, headers=headers)
    assert r.status_code == 422


def test_non_admin_cannot_reach_the_token_api(client):
    tokens = register_and_login(client, email="plain@zerostrike.dev")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.get("/api/v1/admin/mcp-tokens", headers=headers).status_code == 403
    assert client.post("/api/v1/admin/mcp-tokens", json={"label": "x"}, headers=headers).status_code == 403


def test_issue_and_revoke_are_audited_in_the_privilege_bucket(client):
    headers = _admin(client)
    issued = _issue(client, headers)
    assert client.delete(f"/api/v1/admin/mcp-tokens/{issued['id']}", headers=headers).status_code == 204
    rows = {a.action: a for a in _run(AuditLog.find_all().to_list())}
    assert "MCP credential issued" in rows and "MCP credential revoked" in rows
    from app.services import audit_service

    assert audit_service.classify("MCP credential issued", None) == "privilege"
    assert issued["raw_token"] not in json.dumps(rows["MCP credential issued"].metadata)


def test_an_admin_cannot_see_or_revoke_another_admins_token(client):
    first = _admin(client, "adm1@zerostrike.dev")
    token = _issue(client, first)
    second = _admin(client, "adm2@zerostrike.dev")
    assert client.get("/api/v1/admin/mcp-tokens", headers=second).json() == []
    assert client.delete(f"/api/v1/admin/mcp-tokens/{token['id']}", headers=second).status_code == 404


# --- auth wrapper -----------------------------------------------------------


def test_missing_or_garbage_token_is_401(client):
    assert client.post("/mcp", json={}, headers=MCP_HEADERS).status_code == 401
    assert _rpc(client, "tsmcp_nope", "tools/list").status_code == 401
    r = client.post("/mcp", json={}, headers={**MCP_HEADERS, "Authorization": "Basic abc"})
    assert r.status_code == 401


def test_post_to_mcp_is_not_redirected(client, admin_token):
    _, token = admin_token
    r = _rpc(client, token, "tools/list")
    assert r.status_code == 200  # TestClient follows redirects, so also assert the route is exact
    assert r.history == []


def test_expired_and_revoked_tokens_are_401(client, admin_token):
    headers, token = admin_token
    stored = _run(McpToken.find_all().to_list())[0]

    async def _expire():
        stored.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await stored.save()

    _run(_expire())
    assert _rpc(client, token, "tools/list").status_code == 401

    fresh = _issue(client, headers)
    assert _rpc(client, fresh["raw_token"], "tools/list").status_code == 200
    client.delete(f"/api/v1/admin/mcp-tokens/{fresh['id']}", headers=headers)
    assert _rpc(client, fresh["raw_token"], "tools/list").status_code == 401


def test_demoted_admin_is_refused_with_403_immediately(client, admin_token):
    _, token = admin_token
    assert _rpc(client, token, "tools/list").status_code == 200

    async def _demote():
        user = await User.find_one(User.email == "mcpadmin@zerostrike.dev")
        user.role = "user"
        await user.save()

    _run(_demote())
    assert _rpc(client, token, "tools/list").status_code == 403


def test_deactivated_admin_is_refused(client, admin_token):
    _, token = admin_token

    async def _disable():
        user = await User.find_one(User.email == "mcpadmin@zerostrike.dev")
        user.is_active = False
        await user.save()

    _run(_disable())
    assert _rpc(client, token, "tools/list").status_code == 403


def test_kill_switch_leaves_mcp_unmounted(monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import create_app

    monkeypatch.setattr(settings, "mcp_enabled", False)
    with TestClient(create_app()) as c:
        assert c.post("/mcp", json={}, headers=MCP_HEADERS).status_code == 404


# --- tools ------------------------------------------------------------------

EXPECTED_TOOLS = {
    "get_system_health", "get_operations_overview", "get_scanner_status", "list_system_logs",
    "get_system_log", "summarize_errors", "trace_request", "list_audit_logs", "inspect_job",
    "list_failed_jobs", "get_ai_health", "get_runtime_config", "get_data_stats", "list_projects",
    "lookup_user",
}


def test_exactly_the_planned_tools_are_listed_and_read_only(client, admin_token):
    _, token = admin_token
    tools = _rpc(client, token, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == EXPECTED_TOOLS
    assert all(t["annotations"]["readOnlyHint"] for t in tools)


def _seed_logs():
    async def _seed():
        now = datetime.now(timezone.utc)
        rows = [
            SystemLog(level="error", logger="app.scan", message="clone failed: token=ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
                      context={"request_id": "req-1", "scan_id": "scan-1",
                               "clone": {"urls": ["https://u:ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8@h/r"]}},
                      exception="Traceback...\nBoom",
                      created_at=now),
            SystemLog(level="error", logger="app.scan", message="clone failed: token=ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8", context={"request_id": "req-2"},
                      created_at=now - timedelta(minutes=1)),
            SystemLog(level="warning", logger="app.other", message="slow" + "x" * 5000, created_at=now - timedelta(minutes=2)),
            SystemLog(level="error", logger="app.old", message="ancient", created_at=now - timedelta(days=3)),
        ]
        for r in rows:
            await r.insert()
        return [str(r.id) for r in rows]

    return _run(_seed())


def test_system_log_tools_filter_truncate_and_redact(client, admin_token):
    _, token = admin_token
    ids = _seed_logs()

    out = _call(client, token, "list_system_logs", level="error")
    assert out["total"] == 2  # warning below the floor, old row outside the window
    assert "ghp_a1B2" not in json.dumps(out)

    assert _call(client, token, "list_system_logs", request_id="req-1")["total"] == 1
    assert _call(client, token, "list_system_logs", scan_id="scan-1")["total"] == 1
    assert _call(client, token, "list_system_logs", contains="CLONE FAILED")["total"] == 2
    assert _call(client, token, "list_system_logs", logger="app.other")["items"][0]["message"].endswith("[truncated]")

    full = _call(client, token, "get_system_log", id=ids[0])
    assert full["exception"].startswith("Traceback") and full["context"]["request_id"] == "req-1"
    assert "ghp_a1B2" not in json.dumps(full)

    groups = _call(client, token, "summarize_errors")["groups"]
    assert {g["logger"] for g in groups} == {"app.scan"}
    assert groups[0]["count"] == 2 and groups[0]["sample_id"]

    trace = _call(client, token, "trace_request", request_id="req-1")
    assert [r["id"] for r in trace["system_logs"]] == [ids[0]]


def test_limit_is_capped_at_200(client, admin_token):
    _, token = admin_token

    async def _seed():
        await SystemLog.insert_many(
            [SystemLog(level="error", logger="l", message=f"m{i}", created_at=datetime.now(timezone.utc)) for i in range(205)]
        )

    _run(_seed())
    assert len(_call(client, token, "list_system_logs", level="error", limit=100000)["items"]) == 200
    assert len(_call(client, token, "list_system_logs", level="error", limit=3)["items"]) == 3
    assert mcp_server._cap(0) == 1


def test_bad_arguments_are_tool_errors_not_server_errors(client, admin_token):
    _, token = admin_token
    r = _rpc(client, token, "tools/call", {"name": "list_system_logs", "arguments": {"level": "nope"}})
    assert r.status_code == 200 and r.json()["result"]["isError"] is True


def test_each_tool_call_writes_an_audit_row(client, admin_token):
    _, token = admin_token
    _call(client, token, "lookup_user", email_or_id="mcpadmin@zerostrike.dev")
    rows = [a for a in _run(AuditLog.find_all().to_list()) if a.action == "MCP tool called"]
    assert len(rows) == 1
    assert rows[0].actor_user_id and rows[0].metadata["tool"] == "lookup_user"
    assert rows[0].metadata["arguments"] == {"email_or_id": "mcpadmin@zerostrike.dev"}


def test_audit_log_tool_filters(client, admin_token):
    _, token = admin_token

    async def _seed():
        for action in ("Scan failed", "User role changed", "Settings updated"):
            await AuditLog(actor_type="system", action=action).insert()

    _run(_seed())
    out = _call(client, token, "list_audit_logs", failures_only=True)
    assert [i["action"] for i in out["items"]] == ["Scan failed"]
    out = _call(client, token, "list_audit_logs", category="privilege", action_contains="role")
    assert [i["action"] for i in out["items"]] == ["User role changed"]
    assert out["items"][0]["category"] == "privilege"


def test_lookup_user_returns_role_status_only_and_no_secrets(client, admin_token):
    _, token = admin_token
    out = _call(client, token, "lookup_user", email_or_id="mcpadmin@zerostrike.dev")
    assert out["role"] == "admin" and out["is_active"] is True and out["approval_status"] == "approved"
    assert not {"password_hash", "refresh_tokens", "name"} & out.keys()
    by_id = _call(client, token, "lookup_user", email_or_id=out["id"])
    assert by_id["email"] == out["email"]
    r = _rpc(client, token, "tools/call", {"name": "lookup_user", "arguments": {"email_or_id": "ghost@zerostrike.dev"}})
    assert r.json()["result"]["isError"] is True


def test_project_job_and_stats_tools(client, admin_token):
    headers, token = admin_token
    project = client.post("/api/v1/projects", json={"name": "Demo"}, headers=headers).json()

    async def _scan():
        from app.models.scan import Scan

        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id=project["id"], scan_type="cloud", status="failed", repo_url="https://example.invalid/r.git",
            repo_token="SUPERSECRET-clone-token", error_message="boom", created_at=now, updated_at=now,
            completed_at=now,
        )
        await scan.insert()
        return str(scan.id)

    scan_id = _run(_scan())

    projects = _call(client, token, "list_projects")["items"]
    assert projects[0]["name"] == "Demo" and projects[0]["member_count"] >= 1
    assert projects[0]["last_scan"]["status"] == "failed"

    job = _call(client, token, "inspect_job", kind="cloud_scan", id=scan_id)
    assert job["status"] == "failed" and job["project_name"] == "Demo" and job["error_message"] == "boom"
    assert "SUPERSECRET" not in json.dumps(job)
    bad = _rpc(client, token, "tools/call", {"name": "inspect_job", "arguments": {"kind": "nope", "id": scan_id}})
    assert bad.json()["result"]["isError"] is True
    # The agent must see why, or it cannot correct the call (a bare ValueError reaches it only as
    # "Error executing tool inspect_job").
    assert "cloud_scan" in bad.json()["result"]["content"][0]["text"]

    failed = _call(client, token, "list_failed_jobs")["items"]
    assert [j["ref_id"] if "ref_id" in j else j.get("id") for j in failed] and failed[0]["error_message"] == "boom"

    stats = _call(client, token, "get_data_stats", project_id=project["id"])["categories"]
    assert {c["key"] for c in stats} >= {"projects", "scan_data"}


def test_runtime_config_is_an_allow_list_with_no_secrets(client, admin_token, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "smtp_password", "SMTP-PASSWORD-VALUE")
    monkeypatch.setattr(settings, "github_client_secret", "GH-SECRET-VALUE")
    monkeypatch.setattr(settings, "mongodb_uri", "mongodb://user:DBPASSWORD@host")
    _, token = admin_token
    out = _call(client, token, "get_runtime_config")
    blob = json.dumps(out)
    for secret in ("SMTP-PASSWORD-VALUE", "GH-SECRET-VALUE", "DBPASSWORD", settings.jwt_secret, settings.oauth_encryption_key):
        assert secret not in blob
    assert out["configured"]["oauth_encryption_key"] is True
    assert out["settings"]["scan_timeout_seconds"] == settings.scan_timeout_seconds
    assert "email_templates" not in out["workspace"]


def test_overview_health_scanner_and_ai_tools_have_the_expected_shape(client, admin_token):
    _, token = admin_token
    overview = _call(client, token, "get_operations_overview")
    assert {q["kind"] for q in overview["queues"]} == {"cloud_scan", "ai_analysis", "remediation", "compliance"}
    health = _call(client, token, "get_system_health")
    assert {"mongo", "scanner_binary_present", "queues", "system", "errors_last_hour"} <= health.keys()
    assert health["mongo"] is True
    assert {"engine_available", "binaries", "queue"} <= _call(client, token, "get_scanner_status").keys()
    ai = _call(client, token, "get_ai_health")
    assert "analytics" in ai and ai["recent_failed_calls"] == []


def test_an_admin_can_rename_their_own_token_and_it_is_audited(client):
    headers = _admin(client)
    issued = _issue(client, headers, label="old name")
    r = client.patch(f"/api/v1/admin/mcp-tokens/{issued['id']}", json={"label": "  new name "}, headers=headers)
    assert r.status_code == 200 and r.json()["label"] == "new name"
    assert r.json()["prefix"] == issued["prefix"] and r.json()["is_active"] is True
    assert client.patch(f"/api/v1/admin/mcp-tokens/{issued['id']}", json={"label": ""}, headers=headers).status_code == 422
    assert "MCP credential renamed" in {a.action for a in _run(AuditLog.find_all().to_list())}


def test_an_admin_cannot_rename_another_admins_token(client):
    first = _issue(client, _admin(client, "ren1@zerostrike.dev"))
    other = _admin(client, "ren2@zerostrike.dev")
    assert client.patch(f"/api/v1/admin/mcp-tokens/{first['id']}", json={"label": "x"}, headers=other).status_code == 404

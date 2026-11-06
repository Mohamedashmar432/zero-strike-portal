"""Admin MCP full-portal read tools (docs/ADMIN_MCP.md, "Full-portal read tools"): happy paths,
limit cap, refusal, audit, and one test that no credential-shaped field or value escapes any of them."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.core.security import encrypt_secret
from app.mcp import server as mcp_server
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.ai_usage_event import AIUsageEvent
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.compliance_audit import ComplianceAudit
from app.models.finding import Finding, LocationEmbedded, SecretEmbedded
from app.models.project import Project
from app.models.scan import Scan
from app.models.scan_engine import CustomRule, RuleOverride, RulePackVersion
from app.models.user import User
from app.models.vulnerability import FindingReview, Vulnerability
from app.models.webhook_channel import WebhookChannel
from tests.test_mcp import _admin, _call, _issue, _rpc, _run
from tests.test_users import _promote_to_admin  # noqa: F401  (kept next to the helpers it pairs with)

NEW_TOOLS = {t.__name__ for t in mcp_server.NEW_TOOLS}

# Values planted in every secret-bearing field; none may appear in any tool output.
PLANTED = {
    "password_hash": "PLANTED-pw-hash-0001",
    "refresh_hash": "PLANTED-refresh-token-hash-0002",
    "api_key_hash": "PLANTED-api-key-hash-0003",
    "webhook_url": "https://hooks.planted.example/secret-path-0004",
    "project_webhook": "https://hooks.planted.example/project-secret-0005",
    "repo_token": "PLANTED-repo-token-0006",
    "secret_value": "AKIAPLANTEDSECRET0007",
    "provider_key": "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8",
}
FORBIDDEN_KEYS = ("password_hash", "token_hash", "key_hash", "url_enc", "alert_webhook_enc", "repo_token",
                  "api_key_encrypted", "api_key_secret_name", "refresh_tokens")


@pytest.fixture()
def seeded(client):
    headers = _admin(client)
    token = _issue(client, headers)["raw_token"]
    project = client.post("/api/v1/projects", json={"name": "Seeded"}, headers=headers).json()
    pid = project["id"]

    async def _seed():
        now = datetime.now(timezone.utc)
        member = User(
            email="member@zerostrike.dev", password_hash=PLANTED["password_hash"], name="Member",
            created_at=now, updated_at=now, refresh_tokens=[],
        )
        await member.insert()
        p = await Project.get(pid)
        p.alert_webhook_enc = encrypt_secret(PLANTED["project_webhook"])
        p.alert_emails = ["alerts@zerostrike.dev"]
        p.ai_budget_usd_monthly = 10.0
        await p.save()
        scan = Scan(
            project_id=pid, scan_type="cloud", status="completed", repo_url="https://example.invalid/r.git",
            repo_token=PLANTED["repo_token"], scanner_version="1.2.3", ci_provider="github_actions",
            ci_build_number="42", rule_pack_version=1, created_at=now, updated_at=now,
        )
        await scan.insert()
        sid = str(scan.id)
        loc = LocationEmbedded(file="src/app.py", start_line=3)
        code = Finding(
            scan_id=sid, project_id=pid, fingerprint="fp-code", rule_id="ZS-NOISY", rule_name="Noisy", kind="sast",
            severity="high", message="sql injection", location=loc,
        )
        sec = Finding(
            scan_id=sid, project_id=pid, fingerprint="fp-sec", rule_id="ZS-SECRET", rule_name="Secret", kind="secret",
            severity="critical", message=f"found {PLANTED['secret_value']}", location=loc,
            secret=SecretEmbedded(redacted="AKIA****"), metadata={"raw": PLANTED["secret_value"]},
        )
        await code.insert()
        await sec.insert()
        vulns = []
        for i in range(6):
            v = Vulnerability(
                project_id=pid, repo_scope_key="unlinked", fingerprint=f"v{i}", status="resolved",
                resolution_reason="false_positive", resolved_by_user_id=str(member.id), resolved_at=now,
                resolution_comment="test code", current_rule_id="ZS-NOISY", current_rule_name="Noisy",
                current_severity="high", current_kind="sast", current_message="sql injection",
                current_location=loc, current_scan_id=sid, first_seen_at=now, last_seen_at=now,
            )
            await v.insert()
            vulns.append(v)
        secret_v = Vulnerability(
            project_id=pid, repo_scope_key="unlinked", fingerprint="fp-sec", status="open",
            current_rule_id="ZS-SECRET", current_kind="secret", current_severity="critical",
            current_message=f"found {PLANTED['secret_value']}", current_location=loc, current_scan_id=sid,
            first_seen_at=now, last_seen_at=now,
            review=FindingReview(
                kind="accepted_risk", file_path="src/app.py", requested_by_user_id=str(member.id),
                requested_at=now, request_comment="please",
            ),
        )
        await secret_v.insert()
        await ApiKey(
            project_id=pid, label="ci", prefix="zs_abcd", key_hash=PLANTED["api_key_hash"], created_by="u",
            created_at=now, expires_at=now + timedelta(days=30),
        ).insert()
        await WebhookChannel(name="Teams", url_enc=encrypt_secret(PLANTED["webhook_url"]), events=["scan.failed"]).insert()
        await RuleOverride(rule_id="ZS-OLD", state="retired", reason="noisy", updated_by="a").insert()
        await CustomRule(
            rule_id="ZS-CUSTOM-1", yaml="id: x", vulnerable_sample="a", safe_sample="b", language="python",
            last_validated_at=now, created_by="a",
        ).insert()
        await RulePackVersion(version=1, retired_rule_ids=["ZS-OLD"], changelog="first", published_by="a").insert()
        await ComplianceAudit(
            project_id=pid, frameworks=["soc2"], scope="latest", depth="deterministic", status="completed",
        ).insert()
        await AIFixProposal(finding_id=str(code.id), scan_id=sid, project_id=pid, patched_code="SECRET-DIFF").insert()
        await RemediationJob(
            kind="propose", project_id=pid, scan_id=sid, scope_key="k", trace_id="t", status="failed",
            error_message=f"boom {PLANTED['provider_key']}",
        ).insert()
        await AIUsageEvent(project_id=pid, provider="openai", feature="analysis", created_at=now).insert()
        return sid, str(member.id)

    sid, member_id = _run(_seed())
    return client, token, headers, pid, sid, member_id


def _all_calls(pid, sid, member_id):
    """Every new tool called with arguments that reach the seeded data."""
    return {
        "list_scan_rules": {}, "list_noisy_rules": {}, "get_scan_rule": {"rule_id": "ZS-NOISY"},
        "get_rule_pack": {}, "list_scans": {"project_id": pid}, "get_scan": {"id": sid},
        "list_findings": {"scan_id": sid}, "list_vulnerabilities": {"project_id": pid},
        "list_finding_reviews": {}, "list_compliance_audits": {"project_id": pid},
        "list_fix_proposals": {"project_id": pid}, "list_remediation_jobs": {"project_id": pid},
        "get_ai_usage": {}, "get_ai_budgets": {}, "list_users": {}, "list_webhook_channels": {},
        "get_digest_status": {}, "get_live_alert_status": {}, "get_project": {"id": pid},
        "list_api_keys": {"project_id": pid},
    }


def test_new_tools_are_registered_and_read_only(seeded):
    client, token, *_ = seeded
    tools = {t["name"]: t for t in _rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert NEW_TOOLS <= tools.keys() and len(NEW_TOOLS) == 22
    assert all(t["annotations"]["readOnlyHint"] for t in tools.values())


def test_every_new_tool_returns_data_and_no_secrets(seeded):
    client, token, headers, pid, sid, member_id = seeded
    calls = _all_calls(pid, sid, member_id)
    # get_finding / get_compliance_audit need ids; the rest are covered above.
    code = next(f for f in _run(Finding.find_all().to_list()) if f.kind == "sast")
    sec = next(f for f in _run(Finding.find_all().to_list()) if f.kind == "secret")
    audit = _run(ComplianceAudit.find_all().to_list())[0]
    calls["get_finding"] = {"id": str(code.id)}
    calls["get_compliance_audit"] = {"id": str(audit.id)}
    outputs = {name: _call(client, token, name, **args) for name, args in calls.items()}
    outputs["get_finding_secret"] = _call(client, token, "get_finding", id=str(sec.id))
    assert set(calls) == NEW_TOOLS
    blob = json.dumps(outputs)
    for label, value in PLANTED.items():
        assert value not in blob, label
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in blob, key
    # Spend-bearing and code content stay out too.
    assert "SECRET-DIFF" not in blob
    secret_out = outputs["get_finding_secret"]
    assert "evidence" not in secret_out and "metadata" not in secret_out
    assert secret_out["secret"]["redacted"] == "AKIA****"


def test_scan_engine_tools(seeded):
    client, token, _, pid, *_ = seeded
    rules = _call(client, token, "list_scan_rules")
    assert rules["active_pack_version"] == 1 and rules["items"][0]["rule_id"] == "ZS-NOISY"
    assert "ZS-SECRET" in [r["rule_id"] for r in _call(client, token, "list_scan_rules", query="secret")["items"]]
    assert {r["state"] for r in _call(client, token, "list_scan_rules", state="retired")["items"]} == {"retired"}
    noisy = _call(client, token, "list_noisy_rules")
    assert [r["rule_id"] for r in noisy["items"]] == ["ZS-NOISY"] and noisy["total_noisy"] == 1
    assert [r["rule_id"] for r in _call(client, token, "list_scan_rules", noisy_only=True)["items"]] == ["ZS-NOISY"]
    detail = _call(client, token, "get_scan_rule", rule_id="ZS-NOISY")
    assert detail["rule"]["fp_tags"] == 6 and len(detail["fp_history"]) == 6
    assert detail["fp_history"][0]["project_name"] == "Seeded" and detail["fp_history"][0]["tagged_by"] == "member@zerostrike.dev"
    assert _call(client, token, "get_scan_rule", rule_id="ZS-CUSTOM-1")["custom_rule"]["language"] == "python"
    bad = _rpc(client, token, "tools/call", {"name": "get_scan_rule", "arguments": {"rule_id": "nope"}})
    assert bad.json()["result"]["isError"] is True
    pack = _call(client, token, "get_rule_pack")
    assert pack["active"]["version"] == 1 and pack["active"]["retired_rule_ids"] == ["ZS-OLD"]
    assert pack["has_pending_changes"] is True and pack["pending_changes"]["custom_added"] == ["ZS-CUSTOM-1"]


def test_scan_finding_and_vulnerability_tools(seeded):
    client, token, _, pid, sid, _ = seeded
    scans = _call(client, token, "list_scans", status="completed", scan_type="cloud")
    assert scans["total"] == 1 and scans["items"][0]["scanner_version"] == "1.2.3"
    assert _call(client, token, "list_scans", status="failed")["items"] == []
    scan = _call(client, token, "get_scan", id=sid)
    assert scan["ci_provider"] == "github_actions" and scan["finding_count"] == 2
    findings = _call(client, token, "list_findings", scan_id=sid)
    assert findings["total"] == 2
    secret_row = next(f for f in findings["items"] if f["kind"] == "secret")
    assert secret_row["message"] is None
    vulns = _call(client, token, "list_vulnerabilities", project_id=pid, status="open")
    assert [v["rule_id"] for v in vulns["items"]] == ["ZS-SECRET"] and vulns["items"][0]["message"] is None
    reviews = _call(client, token, "list_finding_reviews")
    assert reviews["pending_count"] == 1 and reviews["items"][0]["rule_id"] == "ZS-SECRET"
    assert reviews["items"][0]["message"] is None
    assert _call(client, token, "list_finding_reviews", status="accepted")["items"] == []


def test_project_policy_users_channels_and_keys(seeded):
    client, token, _, pid, *_ = seeded
    proj = _call(client, token, "get_project", id=pid)
    assert proj["alerts"]["webhook_configured"] is True and proj["alerts"]["webhook_host"] == "hooks.planted.example"
    assert proj["alerts"]["email_count"] == 1 and "alert_emails" not in json.dumps(proj)
    assert set(proj["effective"]) == {"scan_options", "compliance", "remediation", "live_alerts"}
    assert isinstance(proj["effective"]["compliance"]["overridden"], list)
    users = _call(client, token, "list_users", role="user")
    assert [u["email"] for u in users["items"]] == ["member@zerostrike.dev"]
    assert _call(client, token, "list_users", status="pending")["items"] == []
    channels = _call(client, token, "list_webhook_channels")["items"]
    assert channels[0]["host"] == "hooks.planted.example" and channels[0]["events"] == ["scan.failed"]
    keys = _call(client, token, "list_api_keys", project_id=pid)["items"]
    assert keys[0]["prefix"] == "zs_abcd" and "key_hash" not in keys[0]
    assert _call(client, token, "get_digest_status")["enabled"] is False
    assert "ecosystems" in _call(client, token, "get_live_alert_status")


def test_compliance_autofix_and_ai_tools(seeded):
    client, token, _, pid, *_ = seeded
    audits = _call(client, token, "list_compliance_audits")
    assert audits["total"] == 1 and audits["items"][0]["frameworks"] == ["soc2"]
    assert _call(client, token, "get_compliance_audit", id=audits["items"][0]["id"])["id"] == audits["items"][0]["id"]
    proposals = _call(client, token, "list_fix_proposals", project_id=pid)
    assert proposals["total"] == 1 and "patched_code" not in proposals["items"][0]
    jobs = _call(client, token, "list_remediation_jobs", status="failed")
    assert jobs["items"][0]["kind"] == "propose" and PLANTED["provider_key"] not in json.dumps(jobs)
    assert _call(client, token, "get_ai_usage", days=7)["analytics"]
    budgets = _call(client, token, "get_ai_budgets")
    assert budgets["items"][0]["limit_usd_monthly"] == 10.0


def test_new_list_tools_cap_limit_at_200(seeded):
    client, token, _, pid, sid, _ = seeded

    async def _more():
        now = datetime.now(timezone.utc)
        await Scan.insert_many(
            [Scan(project_id=pid, scan_type="cicd", status="completed", created_at=now, updated_at=now) for _ in range(205)]
        )

    _run(_more())
    assert len(_call(client, token, "list_scans", limit=100000)["items"]) == 200
    assert len(_call(client, token, "list_scans", limit=2)["items"]) == 2


def test_each_new_tool_call_is_audited(seeded):
    client, token, _, pid, *_ = seeded
    _call(client, token, "list_scans", project_id=pid, limit=5)
    rows = [a for a in _run(AuditLog.find_all().to_list()) if a.action == "MCP tool called"]
    assert rows[-1].metadata["tool"] == "list_scans"
    assert rows[-1].metadata["arguments"] == {"project_id": pid, "limit": 5}


def test_new_tools_still_refuse_non_admin_and_demoted_admin(seeded):
    client, token, *_ = seeded
    assert _rpc(client, "tsmcp_garbage", "tools/call", {"name": "list_users", "arguments": {}}).status_code == 401

    async def _demote():
        u = await User.find_one(User.email == "mcpadmin@zerostrike.dev")
        u.role = "user"
        await u.save()

    _run(_demote())
    r = _rpc(client, token, "tools/call", {"name": "list_users", "arguments": {}})
    assert r.status_code == 403
    assert not [a for a in _run(AuditLog.find_all().to_list()) if a.metadata.get("tool") == "list_users"]


def test_scrub_drops_credential_shaped_keys_even_if_a_tool_forgot():
    dirty = {"ok": 1, "password_hash": "x", "nested": [{"url_enc": "x", "key_hash": "y", "label": "k"}], "repo_token": "t"}
    assert mcp_server._scrub(dirty) == {"ok": 1, "nested": [{"label": "k"}]}

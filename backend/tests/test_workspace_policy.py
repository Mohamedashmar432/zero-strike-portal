"""Workspace defaults, project overrides, and the tighten-only rule between them.

The rule under test everywhere here: `None` on a Project means inherit, and an override may
only tighten workspace policy — never loosen it. If that breaks, a project owner silently
gains the ability to weaken a safety gate a portal admin set.
"""

import asyncio
from datetime import datetime, timezone

from app.models.project import Project
from app.services import workspace_settings_service as wss
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

WS_URL = "/api/v1/workspace-settings"


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Policy Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


# --- workspace surface -------------------------------------------------------


def test_workspace_settings_lazily_created_with_todays_behaviour_as_defaults(client):
    admin = _admin_headers(client, email="wp-defaults@zs.dev")
    body = client.get(WS_URL, headers=admin).json()
    # All three analysers default on — these mirror the flags that used to be hardcoded into
    # the scanner argv, so an existing workspace behaves identically until someone edits them.
    assert body["scan_enable_secrets"] is True
    assert body["scan_enable_sca"] is True
    assert body["scan_enable_framework_checks"] is True
    assert body["compliance_frameworks"] == []
    assert body["compliance_auto_audit_on_scan"] is False
    assert body["compliance_evidence_retention_days"] is None


def test_any_member_may_read_workspace_settings_but_only_admin_writes(client):
    _admin_headers(client, email="wp-rw-admin@zs.dev")
    user = _headers(register_and_login(client, email="wp-rw-user@zs.dev"))
    # Readable: a project owner cannot decide what to override without seeing what they inherit.
    assert client.get(WS_URL, headers=user).status_code == 200
    assert client.put(WS_URL, json={"scan_enable_sca": False}, headers=user).status_code == 403


def test_workspace_update_is_partial_and_audited(client):
    admin = _admin_headers(client, email="wp-update@zs.dev")
    r = client.put(WS_URL, json={"scan_enable_sca": False}, headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["scan_enable_sca"] is False
    assert body["scan_enable_secrets"] is True  # untouched field keeps its value

    logs = client.get("/api/v1/audit-logs", headers=admin).json()
    assert any(item["action"] == "Workspace Settings Updated" for item in logs["items"])


def test_unsupported_framework_is_rejected(client):
    admin = _admin_headers(client, email="wp-framework@zs.dev")
    r = client.put(WS_URL, json={"compliance_frameworks": ["hipaa"]}, headers=admin)
    # Storing it would let a saved policy pre-select a framework the audit endpoint refuses.
    assert r.status_code == 422
    assert client.put(WS_URL, json={"compliance_frameworks": ["soc2"]}, headers=admin).status_code == 200


# --- project surface ---------------------------------------------------------


def test_project_policy_reports_inherited_values_before_any_override(client):
    admin = _admin_headers(client, email="wp-inherit@zs.dev")
    client.put(WS_URL, json={"scan_enable_secrets": False}, headers=admin)
    project = _create_project(client, admin, name="Inheriting")

    body = client.get(f"/api/v1/projects/{project['id']}/policy", headers=admin).json()
    assert body["scan_enable_secrets"] is None  # no override
    assert body["effective_scan_enable_secrets"] is False  # but the workspace value applies


def test_collaborator_cannot_write_project_policy(client):
    admin = _admin_headers(client, email="wp-collab-admin@zs.dev")
    project = _create_project(client, admin, name="Collab")
    collaborator = register_and_login(client, email="wp-collab@zs.dev")
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "wp-collab@zs.dev", "role": "collaborator"},
        headers=admin,
    )
    h = _headers(collaborator)
    url = f"/api/v1/projects/{project['id']}/policy"
    assert client.get(url, headers=h).status_code == 200
    assert client.get(url, headers=h).json()["can_manage"] is False
    assert client.put(url, json={"scan_enable_sca": False}, headers=h).status_code == 403


def test_explicit_null_clears_an_override(client):
    admin = _admin_headers(client, email="wp-clear@zs.dev")
    project = _create_project(client, admin, name="Clearing")
    url = f"/api/v1/projects/{project['id']}/policy"

    assert client.put(url, json={"scan_enable_sca": False}, headers=admin).json()["scan_enable_sca"] is False
    # An explicit null is a real edit — "stop overriding" — not an absent field.
    assert client.put(url, json={"scan_enable_sca": None}, headers=admin).json()["scan_enable_sca"] is None
    assert client.get(url, headers=admin).json()["effective_scan_enable_sca"] is True


# --- the tighten-only rule ---------------------------------------------------


def test_project_may_disable_auto_fix_but_not_enable_it_against_the_workspace(client):
    admin = _admin_headers(client, email="wp-tighten-enabled@zs.dev")
    project = _create_project(client, admin, name="Tighten Enabled")
    url = f"/api/v1/projects/{project['id']}/policy"

    # Workspace on, project off -> off.
    assert client.put(url, json={"auto_fix_enabled": False}, headers=admin).json()[
        "effective_auto_fix_enabled"
    ] is False

    # Workspace off, project on -> still off. The project cannot loosen the workspace.
    client.put("/api/v1/remediation-settings/settings", json={"enabled": False}, headers=admin)
    assert client.put(url, json={"auto_fix_enabled": True}, headers=admin).json()[
        "effective_auto_fix_enabled"
    ] is False


def test_project_may_raise_the_confidence_bar_but_never_lower_it(client):
    admin = _admin_headers(client, email="wp-tighten-threshold@zs.dev")
    client.put(
        "/api/v1/remediation-settings/settings", json={"confidence_threshold": 80}, headers=admin
    )
    project = _create_project(client, admin, name="Tighten Threshold")
    url = f"/api/v1/projects/{project['id']}/policy"

    assert client.put(url, json={"auto_fix_confidence_threshold": 95}, headers=admin).json()[
        "effective_auto_fix_confidence_threshold"
    ] == 95
    # A lower number is stored but never takes effect — the effective bar is the higher of the two.
    body = client.put(url, json={"auto_fix_confidence_threshold": 10}, headers=admin).json()
    assert body["auto_fix_confidence_threshold"] == 10
    assert body["effective_auto_fix_confidence_threshold"] == 80


# --- resolver-level checks ---------------------------------------------------


def test_load_project_returns_none_for_a_malformed_id_rather_than_raising(client):
    async def run():
        # Beanie's .get() raises on a non-ObjectId. A scan whose project_id is stale must not
        # fail the whole scan just because policy could not be resolved.
        assert await wss.load_project("not-an-object-id") is None
        assert await wss.load_project(None) is None

    asyncio.run(run())


def test_scan_options_fall_back_to_workspace_when_project_is_unknown(client):
    async def run():
        await wss.update_workspace_settings(scan_enable_secrets=False)
        options = await wss.effective_scan_options(None)
        assert options.enable_secrets is False
        assert options.enable_sca is True

    asyncio.run(run())


def test_compliance_policy_reports_which_fields_were_overridden(client):
    async def run():
        await wss.update_workspace_settings(compliance_frameworks=["soc2"])
        project = Project(
            name="Overridden",
            owner_id="someone",
            compliance_auto_audit_on_scan=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await project.insert()

        policy = await wss.effective_compliance_policy(project)
        assert policy.frameworks == ["soc2"]  # inherited
        assert policy.auto_audit_on_scan is True  # overridden
        assert policy.overridden == frozenset({"auto_audit_on_scan"})

    asyncio.run(run())

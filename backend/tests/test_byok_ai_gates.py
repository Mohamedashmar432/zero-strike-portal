"""Regression cover for the "is AI available?" gates under Project BYOK.

These gates sit *in front of* llm_client, so llm_client resolving correctly is not enough: each
gate independently decided whether AI was usable, and each of them used to answer by looking only
at the portal-wide provider. With BYOK on and no portal provider, a project holding a perfectly
good key of its own was told AI was unconfigured -- everywhere.
"""

from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Gate Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _enable_byok(client, admin_headers):
    r = client.put(
        "/api/v1/ai/settings", json={"project_byok_enabled": True}, headers=admin_headers
    )
    assert r.status_code == 200


def _add_project_key(client, headers, project_id):
    r = client.post(
        f"/api/v1/projects/{project_id}/ai-provider",
        json={
            "name": "Project key",
            "provider": "anthropic",
            "model_name": "claude-haiku-4-5",
            "api_key": "sk-project",
        },
        headers=headers,
    )
    assert r.status_code == 201
    return r.json()


def test_connection_error_messages_are_actionable_not_raw_exceptions():
    """A project owner testing their own key gets a verdict on what they typed. str(exc) would put
    litellm's repr, the provider's JSON body and a request id into a toast."""
    import app.services.llm_client as llm_client

    cases = {
        'litellm.AuthenticationError: AnthropicException - {"type":"authentication_error"}': "API key",
        "litellm.NotFoundError: model claude-nope does not exist": "model id",
        "litellm.RateLimitError: quota exceeded for this key": "rate-limiting",
    }
    for raw, expected_fragment in cases.items():
        msg = llm_client.connection_error_message(llm_client.LLMPermanentError(raw))
        assert expected_fragment in msg
        # Never leak the provider's raw payload or litellm internals to the UI.
        assert "litellm" not in msg and "{" not in msg

    unreachable = llm_client.connection_error_message(llm_client.LLMTransientError("connection reset"))
    assert "base URL" in unreachable

    not_configured = llm_client.connection_error_message(llm_client.LLMNotConfiguredError("x"))
    assert "provider and model" in not_configured


def test_ai_status_is_answered_per_project_under_byok(client):
    admin_headers = _admin_headers(client, email="gate-admin1@zerostrike.dev")
    owner = register_and_login(client, email="gate-owner1@zerostrike.dev")
    with_key = _create_project(client, _headers(owner), name="Has key")
    without_key = _create_project(client, _headers(owner), name="No key")

    _enable_byok(client, admin_headers)
    _add_project_key(client, _headers(owner), with_key["id"])

    # No portal-wide provider exists at all, yet the project with its own key must report enabled.
    enabled = client.get(
        "/api/v1/ai/status", params={"project_id": with_key["id"]}, headers=_headers(owner)
    ).json()
    assert enabled["enabled"] is True

    disabled = client.get(
        "/api/v1/ai/status", params={"project_id": without_key["id"]}, headers=_headers(owner)
    ).json()
    assert disabled["enabled"] is False


def test_ai_status_without_byok_is_unchanged(client):
    admin_headers = _admin_headers(client, email="gate-admin2@zerostrike.dev")
    owner = register_and_login(client, email="gate-owner2@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    assert client.get("/api/v1/ai/status", headers=_headers(owner)).json()["enabled"] is False

    client.post(
        "/api/v1/ai/providers",
        json={
            "name": "Portal",
            "provider": "anthropic",
            "model_name": "claude-haiku-4-5",
            "api_key": "sk-portal",
        },
        headers=admin_headers,
    )

    # BYOK off: the portal provider serves every project, with or without a project_id.
    assert client.get("/api/v1/ai/status", headers=_headers(owner)).json()["enabled"] is True
    assert (
        client.get(
            "/api/v1/ai/status", params={"project_id": project["id"]}, headers=_headers(owner)
        ).json()["enabled"]
        is True
    )


def test_compliance_ai_narrative_accepts_a_projects_own_key(client):
    """The audit gate used to 409 on a BYOK project because it checked the portal provider."""
    admin_headers = _admin_headers(client, email="gate-admin3@zerostrike.dev")
    owner = register_and_login(client, email="gate-owner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    _enable_byok(client, admin_headers)

    body = {"frameworks": ["soc2"], "scope": "latest", "depth": "with_ai_narrative"}
    url = f"/api/v1/projects/{project['id']}/compliance-audits"

    # No key yet -> refused, and the message points at the project's own settings page.
    refused = client.post(url, json=body, headers=_headers(owner))
    assert refused.status_code == 409
    assert "Project → Settings → AI Provider" in refused.json()["detail"]

    _add_project_key(client, _headers(owner), project["id"])

    # With its own key the AI gate no longer blocks (any later failure is about scans/evidence,
    # not provider configuration).
    accepted = client.post(url, json=body, headers=_headers(owner))
    assert accepted.status_code != 409 or "AI Provider" not in accepted.json().get("detail", "")

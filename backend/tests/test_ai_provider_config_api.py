import litellm

from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

BASE = "/api/v1/ai/providers"


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_body(name="Test Provider", api_key="sk-test"):
    return {"name": name, "provider": "openai", "model_name": "gpt-4o", "api_key": api_key}


def test_non_admin_forbidden_on_all_routes(client):
    user = register_and_login(client, email="prov-user@zerostrike.dev")
    headers = _headers(user)

    assert client.get(BASE, headers=headers).status_code == 403
    assert client.post(BASE, json=_create_body(), headers=headers).status_code == 403
    assert client.get(f"{BASE}/507f1f77bcf86cd799439011", headers=headers).status_code == 403
    assert client.put(f"{BASE}/507f1f77bcf86cd799439011", json=_create_body(), headers=headers).status_code == 403
    assert client.delete(f"{BASE}/507f1f77bcf86cd799439011", headers=headers).status_code == 403
    assert client.post(f"{BASE}/507f1f77bcf86cd799439011/activate", headers=headers).status_code == 403
    assert client.post(f"{BASE}/deactivate", headers=headers).status_code == 403
    assert client.post(f"{BASE}/507f1f77bcf86cd799439011/test", headers=headers).status_code == 403
    assert (
        client.post(
            f"{BASE}/test",
            json={"provider": "openai", "model_name": "gpt-4o", "api_key": "sk-x"},
            headers=headers,
        ).status_code
        == 403
    )


def test_full_lifecycle_create_list_get_update_delete(client):
    admin_headers = _admin_headers(client, email="prov-admin1@zerostrike.dev")

    r = client.post(BASE, json=_create_body(name="Primary"), headers=admin_headers)
    assert r.status_code == 201
    created = r.json()
    assert created["is_active"] is True
    assert created["has_api_key"] is True
    assert created["name"] == "Primary"
    assert created["total_requests"] == 0
    assert created["total_failed_requests"] == 0
    assert created["total_prompt_tokens"] == 0
    assert created["total_completion_tokens"] == 0
    assert created["total_cost_usd"] == 0
    assert created["last_used_at"] is None
    assert "api_key" not in created
    assert "api_key_encrypted" not in created
    provider_id = created["id"]

    r = client.get(BASE, headers=admin_headers)
    assert r.status_code == 200
    listed = r.json()
    assert len(listed) == 1
    assert listed[0]["id"] == provider_id
    assert "api_key" not in listed[0]
    assert "api_key_encrypted" not in listed[0]

    r = client.get(f"{BASE}/{provider_id}", headers=admin_headers)
    assert r.status_code == 200
    fetched = r.json()
    assert fetched["id"] == provider_id
    assert "api_key" not in fetched

    r = client.put(
        f"{BASE}/{provider_id}",
        json={"name": "Primary Renamed", "provider": "openai", "model_name": "gpt-4o-mini"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["name"] == "Primary Renamed"
    assert updated["model_name"] == "gpt-4o-mini"
    assert updated["has_api_key"] is True  # api_key omitted -> kept
    assert "api_key" not in updated

    r = client.delete(f"{BASE}/{provider_id}", headers=admin_headers)
    assert r.status_code == 204

    r = client.get(f"{BASE}/{provider_id}", headers=admin_headers)
    assert r.status_code == 404

    r = client.get(BASE, headers=admin_headers)
    assert r.json() == []


def test_activating_one_provider_deactivates_all_others(client):
    admin_headers = _admin_headers(client, email="prov-admin2@zerostrike.dev")

    a = client.post(BASE, json=_create_body(name="A"), headers=admin_headers).json()
    b = client.post(BASE, json=_create_body(name="B"), headers=admin_headers).json()
    assert a["is_active"] is True
    assert b["is_active"] is False

    r = client.post(f"{BASE}/{b['id']}/activate", headers=admin_headers)
    assert r.status_code == 200
    by_id = {item["id"]: item for item in r.json()}
    assert by_id[a["id"]]["is_active"] is False
    assert by_id[b["id"]]["is_active"] is True

    r = client.post(f"{BASE}/deactivate", headers=admin_headers)
    assert r.status_code == 200
    by_id = {item["id"]: item for item in r.json()}
    assert by_id[a["id"]]["is_active"] is False
    assert by_id[b["id"]]["is_active"] is False


def test_deleting_active_provider_flips_status_to_disabled(client):
    admin_headers = _admin_headers(client, email="prov-admin3@zerostrike.dev")
    other_user = register_and_login(client, email="prov-status-user3@zerostrike.dev")

    created = client.post(BASE, json=_create_body(), headers=admin_headers).json()
    assert created["is_active"] is True

    r = client.get("/api/v1/ai/status", headers=_headers(other_user))
    assert r.json()["enabled"] is True

    client.delete(f"{BASE}/{created['id']}", headers=admin_headers)

    r = client.get("/api/v1/ai/status", headers=_headers(other_user))
    assert r.json()["enabled"] is False


def test_key_never_leaks_in_any_response_body(client):
    admin_headers = _admin_headers(client, email="prov-admin4@zerostrike.dev")
    r = client.post(BASE, json=_create_body(api_key="sk-super-secret-value"), headers=admin_headers)
    provider_id = r.json()["id"]
    assert "sk-super-secret-value" not in r.text

    r = client.get(BASE, headers=admin_headers)
    assert "sk-super-secret-value" not in r.text

    r = client.get(f"{BASE}/{provider_id}", headers=admin_headers)
    assert "sk-super-secret-value" not in r.text

    r = client.put(
        f"{BASE}/{provider_id}",
        json={"name": "Renamed", "provider": "openai", "model_name": "gpt-4o", "api_key": "sk-another-secret"},
        headers=admin_headers,
    )
    assert "sk-another-secret" not in r.text
    assert "sk-super-secret-value" not in r.text


def test_test_connection_draft_bad_key_returns_400_and_persists_nothing(client, monkeypatch):
    async def fake_acompletion(**kwargs):
        raise litellm.AuthenticationError(message="bad key", llm_provider="openai", model="gpt-4o")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    admin_headers = _admin_headers(client, email="prov-admin5@zerostrike.dev")
    r = client.post(
        f"{BASE}/test",
        json={"provider": "openai", "model_name": "gpt-4o", "api_key": "sk-bad"},
        headers=admin_headers,
    )
    assert r.status_code == 400
    assert "bad key" in r.json()["detail"]

    r = client.get(BASE, headers=admin_headers)
    assert r.json() == []  # nothing persisted as a side effect


def test_test_connection_stored_provider_bad_key_returns_400(client, monkeypatch):
    async def fake_acompletion(**kwargs):
        raise litellm.AuthenticationError(message="invalid api key", llm_provider="openai", model="gpt-4o")

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    admin_headers = _admin_headers(client, email="prov-admin6@zerostrike.dev")
    created = client.post(BASE, json=_create_body(api_key="sk-stored"), headers=admin_headers).json()

    r = client.post(f"{BASE}/{created['id']}/test", headers=admin_headers)
    assert r.status_code == 400
    assert "invalid api key" in r.json()["detail"]


def test_test_connection_success(client, monkeypatch):
    class _FakeMessage:
        content = "pong"

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        choices = [_FakeChoice()]

    async def fake_acompletion(**kwargs):
        return _FakeResponse()

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)

    admin_headers = _admin_headers(client, email="prov-admin7@zerostrike.dev")
    r = client.post(
        f"{BASE}/test",
        json={"provider": "openai", "model_name": "gpt-4o", "api_key": "sk-good"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["success"] is True

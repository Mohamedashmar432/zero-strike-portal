"""Per-project bring-your-own-key: the global switch, the CRUD behind it, and the isolation
between a project's provider config and everyone else's."""

from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers

AI_SETTINGS = "/api/v1/ai/settings"


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="BYOK Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _enable_byok(client, admin_headers, enabled=True):
    r = client.put(AI_SETTINGS, json={"project_byok_enabled": enabled}, headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["project_byok_enabled"] is enabled


def _provider_body(name="Project Key", api_key="sk-project", model="gpt-4o"):
    return {"name": name, "provider": "openai", "model_name": model, "api_key": api_key}


# --- the global switch ---------------------------------------------------------------------


def test_byok_defaults_off_and_only_admin_can_flip_it(client):
    admin_headers = _admin_headers(client, email="byok-admin0@zerostrike.dev")
    user = register_and_login(client, email="byok-user0@zerostrike.dev")

    assert client.get(AI_SETTINGS, headers=admin_headers).json()["project_byok_enabled"] is False

    # Readable by anyone (a project owner needs it to know whether their BYOK card applies),
    # writable only by an admin.
    assert client.get(AI_SETTINGS, headers=_headers(user)).status_code == 200
    assert (
        client.put(AI_SETTINGS, json={"project_byok_enabled": True}, headers=_headers(user)).status_code
        == 403
    )

    _enable_byok(client, admin_headers)
    assert client.get(AI_SETTINGS, headers=admin_headers).json()["project_byok_enabled"] is True


def test_project_provider_routes_409_while_byok_is_off(client):
    owner = register_and_login(client, email="byok-off@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    base = f"/api/v1/projects/{project['id']}/ai-provider"

    r = client.post(base, json=_provider_body(), headers=_headers(owner))
    assert r.status_code == 409
    assert "disabled by the portal administrator" in r.json()["detail"]

    # Reading the (empty) list is not gated -- only mutations are, so the settings UI can render.
    assert client.get(base, headers=_headers(owner)).json() == []


# --- CRUD + permissions --------------------------------------------------------------------


def test_owner_can_manage_a_project_key_and_it_is_never_returned(client):
    admin_headers = _admin_headers(client, email="byok-admin1@zerostrike.dev")
    _enable_byok(client, admin_headers)
    owner = register_and_login(client, email="byok-owner1@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    base = f"/api/v1/projects/{project['id']}/ai-provider"

    created = client.post(base, json=_provider_body(), headers=_headers(owner))
    assert created.status_code == 201
    body = created.json()
    assert body["has_api_key"] is True
    assert body["project_id"] == project["id"]
    # First provider in a scope auto-activates, same rule as the portal-wide scope.
    assert body["is_active"] is True
    # The raw key and its ciphertext must never leave the server in any form.
    assert "sk-project" not in created.text
    assert "api_key" not in body and "api_key_encrypted" not in body

    updated = client.put(
        f"{base}/{body['id']}",
        json={"name": "Renamed", "provider": "openai", "model_name": "gpt-4o-mini"},
        headers=_headers(owner),
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Renamed"
    # api_key omitted => the stored key survives the edit.
    assert updated.json()["has_api_key"] is True

    assert client.delete(f"{base}/{body['id']}", headers=_headers(owner)).status_code == 204
    assert client.get(base, headers=_headers(owner)).json() == []


def test_collaborator_can_read_but_not_manage(client):
    admin_headers = _admin_headers(client, email="byok-admin2@zerostrike.dev")
    _enable_byok(client, admin_headers)
    owner = register_and_login(client, email="byok-owner2@zerostrike.dev")
    collaborator = register_and_login(client, email="byok-collab2@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    base = f"/api/v1/projects/{project['id']}/ai-provider"

    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "byok-collab2@zerostrike.dev"},
        headers=_headers(owner),
    )
    client.post(base, json=_provider_body(), headers=_headers(owner))

    assert len(client.get(base, headers=_headers(collaborator)).json()) == 1
    assert client.post(base, json=_provider_body(), headers=_headers(collaborator)).status_code == 403


def test_a_project_cannot_touch_another_projects_key(client):
    """The config id is the only thing standing between two tenants' credentials -- without the
    scope check on lookup, knowing an id is enough to read, re-key, activate or delete it."""
    admin_headers = _admin_headers(client, email="byok-admin3@zerostrike.dev")
    _enable_byok(client, admin_headers)
    alice = register_and_login(client, email="byok-alice@zerostrike.dev")
    bob = register_and_login(client, email="byok-bob@zerostrike.dev")
    a = _create_project(client, _headers(alice), name="Alice")
    b = _create_project(client, _headers(bob), name="Bob")

    a_config = client.post(
        f"/api/v1/projects/{a['id']}/ai-provider", json=_provider_body(), headers=_headers(alice)
    ).json()

    b_base = f"/api/v1/projects/{b['id']}/ai-provider/{a_config['id']}"
    assert client.put(b_base, json=_provider_body(), headers=_headers(bob)).status_code == 404
    assert client.delete(b_base, headers=_headers(bob)).status_code == 404
    assert client.post(f"{b_base}/activate", headers=_headers(bob)).status_code == 404
    assert client.post(f"{b_base}/test", headers=_headers(bob)).status_code == 404

    # Alice's config is untouched and still hers alone.
    assert client.get(f"/api/v1/projects/{b['id']}/ai-provider", headers=_headers(bob)).json() == []
    assert len(client.get(f"/api/v1/projects/{a['id']}/ai-provider", headers=_headers(alice)).json()) == 1


def test_project_keys_never_appear_in_the_admin_portal_provider_list(client):
    admin_headers = _admin_headers(client, email="byok-admin4@zerostrike.dev")
    _enable_byok(client, admin_headers)
    owner = register_and_login(client, email="byok-owner4@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    client.post(
        f"/api/v1/projects/{project['id']}/ai-provider",
        json=_provider_body(name="Project Only"),
        headers=_headers(owner),
    )
    portal = client.get("/api/v1/ai/providers", headers=admin_headers).json()
    assert [p["name"] for p in portal] == []


def test_activating_a_project_provider_leaves_the_portal_provider_active(client):
    """Scoped is_active: two scopes each keep their own active config."""
    admin_headers = _admin_headers(client, email="byok-admin5@zerostrike.dev")
    portal = client.post(
        "/api/v1/ai/providers", json=_provider_body(name="Portal"), headers=admin_headers
    ).json()
    assert portal["is_active"] is True

    _enable_byok(client, admin_headers)
    owner = register_and_login(client, email="byok-owner5@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    base = f"/api/v1/projects/{project['id']}/ai-provider"

    first = client.post(base, json=_provider_body(name="P1"), headers=_headers(owner)).json()
    second = client.post(base, json=_provider_body(name="P2"), headers=_headers(owner)).json()
    assert (first["is_active"], second["is_active"]) == (True, False)

    after = client.post(f"{base}/{second['id']}/activate", headers=_headers(owner)).json()
    by_name = {c["name"]: c["is_active"] for c in after}
    assert by_name == {"P1": False, "P2": True}

    still = client.get(f"/api/v1/ai/providers/{portal['id']}", headers=admin_headers).json()
    assert still["is_active"] is True

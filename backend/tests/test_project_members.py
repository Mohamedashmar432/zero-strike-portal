from tests.test_auth_flow import register_and_login


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def _create_project(client, headers, name="Demo"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def test_invite_existing_user_is_accepted_immediately(client):
    owner = register_and_login(client, email="mowner1@zerostrike.dev")
    register_and_login(client, email="collabm1@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    r = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "collabm1@zerostrike.dev"},
        headers=_headers(owner),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "accepted"
    assert body["user_id"] is not None

    members = client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner)).json()
    collaborator = next(m for m in members if m["invited_email"] == "collabm1@zerostrike.dev")
    assert collaborator["name"] == "User"


def test_invite_unregistered_email_is_pending(client):
    owner = register_and_login(client, email="mowner2@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    r = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "notyetregistered@zerostrike.dev"},
        headers=_headers(owner),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["user_id"] is None


def test_pending_invite_links_on_registration(client):
    owner = register_and_login(client, email="mowner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "future3@zerostrike.dev"},
        headers=_headers(owner),
    )

    new_user = register_and_login(client, email="future3@zerostrike.dev")

    r = client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner))
    members = r.json()
    target = next(m for m in members if m["invited_email"] == "future3@zerostrike.dev")
    assert target["status"] == "accepted"

    r = client.get("/api/v1/projects", headers=_headers(new_user))
    assert r.json()["total"] == 1


def test_duplicate_invite_is_conflict(client):
    owner = register_and_login(client, email="mowner4@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "dupe4@zerostrike.dev"},
        headers=_headers(owner),
    )
    r = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "dupe4@zerostrike.dev"},
        headers=_headers(owner),
    )
    assert r.status_code == 409


def test_collaborator_cannot_invite(client):
    # Inviting is an owner/admin-only action — only removing *yourself* is open to any member
    # (see test_member_can_remove_self_but_not_owner and test_only_owner_or_admin_can_change_role
    # below for the other permission boundaries).
    owner = register_and_login(client, email="mowner5@zerostrike.dev")
    collab = register_and_login(client, email="collabm5@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "collabm5@zerostrike.dev"},
        headers=_headers(owner),
    )

    r = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "someoneelse5@zerostrike.dev"},
        headers=_headers(collab),
    )
    assert r.status_code == 403


def test_non_member_cannot_invite(client):
    owner = register_and_login(client, email="mowner5b@zerostrike.dev")
    outsider = register_and_login(client, email="outsider5b@zerostrike.dev")
    project = _create_project(client, _headers(owner))

    r = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "someoneelse5b@zerostrike.dev"},
        headers=_headers(outsider),
    )
    assert r.status_code == 403


def test_member_can_remove_self_but_not_owner(client):
    owner = register_and_login(client, email="mowner6@zerostrike.dev")
    collab = register_and_login(client, email="collabm6@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    invite = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "collabm6@zerostrike.dev"},
        headers=_headers(owner),
    ).json()

    owner_member_id = next(
        m["id"]
        for m in client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner)).json()
        if m["role"] == "owner"
    )
    r = client.delete(
        f"/api/v1/projects/{project['id']}/members/{owner_member_id}", headers=_headers(owner)
    )
    assert r.status_code == 409

    r = client.delete(
        f"/api/v1/projects/{project['id']}/members/{invite['id']}", headers=_headers(collab)
    )
    assert r.status_code == 204


def test_non_member_cannot_remove_others(client):
    owner = register_and_login(client, email="mowner7@zerostrike.dev")
    register_and_login(client, email="collabm7@zerostrike.dev")
    outsider = register_and_login(client, email="outsider7@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    invite = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "collabm7@zerostrike.dev"},
        headers=_headers(owner),
    ).json()

    r = client.delete(
        f"/api/v1/projects/{project['id']}/members/{invite['id']}", headers=_headers(outsider)
    )
    assert r.status_code == 403


def test_owner_can_promote_collaborator_to_owner(client):
    owner = register_and_login(client, email="mowner8@zerostrike.dev")
    register_and_login(client, email="collabm8@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    invite = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "collabm8@zerostrike.dev"},
        headers=_headers(owner),
    ).json()

    r = client.patch(
        f"/api/v1/projects/{project['id']}/members/{invite['id']}",
        json={"role": "owner"},
        headers=_headers(owner),
    )
    assert r.status_code == 200
    assert r.json()["role"] == "owner"


def test_cannot_demote_the_last_owner(client):
    owner = register_and_login(client, email="mowner9@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    owner_member_id = next(
        m["id"]
        for m in client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner)).json()
        if m["role"] == "owner"
    )

    r = client.patch(
        f"/api/v1/projects/{project['id']}/members/{owner_member_id}",
        json={"role": "collaborator"},
        headers=_headers(owner),
    )
    assert r.status_code == 409


def test_collaborator_cannot_change_roles(client):
    owner = register_and_login(client, email="mowner10@zerostrike.dev")
    collab = register_and_login(client, email="collabm10@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    invite = client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "collabm10@zerostrike.dev"},
        headers=_headers(owner),
    ).json()

    r = client.patch(
        f"/api/v1/projects/{project['id']}/members/{invite['id']}",
        json={"role": "owner"},
        headers=_headers(collab),
    )
    assert r.status_code == 403

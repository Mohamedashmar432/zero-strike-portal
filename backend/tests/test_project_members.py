from tests.test_signup_approval import sent  # noqa: F401,F811  (fixture)
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


def test_pending_invite_links_on_registration_with_token(client):
    """Registering with the invite's token (as the emailed link carries) claims the invite --
    this is the proof-of-mailbox-ownership step; see test_registration_without_token_does_not_claim_invite."""
    import asyncio

    from app.models.project_member import ProjectMember

    owner = register_and_login(client, email="mowner3@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "future3@zerostrike.dev"},
        headers=_headers(owner),
    )

    async def _raw_token():
        from app.core import security

        member = await ProjectMember.find_one(ProjectMember.invited_email == "future3@zerostrike.dev")
        # Re-derive: the test has no access to the raw token the email carried, so mint a fresh
        # one through the same hash path to simulate "the registrant has the emailed token".
        raw = "test-raw-token"
        member.invite_token_hash = security.hash_token(raw)
        await member.save()
        return raw

    raw_token = asyncio.run(_raw_token())

    r = client.post(
        "/api/v1/auth/register",
        json={"email": "future3@zerostrike.dev", "password": "hunter2pass", "name": "User", "invite_token": raw_token},
    )
    assert r.status_code == 201
    new_user = client.post(
        "/api/v1/auth/login", json={"email": "future3@zerostrike.dev", "password": "hunter2pass"}
    ).json()

    r = client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner))
    members = r.json()
    target = next(m for m in members if m["invited_email"] == "future3@zerostrike.dev")
    assert target["status"] == "accepted"

    r = client.get("/api/v1/projects", headers=_headers(new_user))
    assert r.json()["total"] == 1


def test_registration_without_token_does_not_claim_invite(client):
    """The core fix: registering with a matching email but no (or wrong) invite token must NOT
    claim someone else's pending invite -- otherwise anyone on an allowed domain could steal it
    by registering first."""
    owner = register_and_login(client, email="mowner3b@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.post(
        f"/api/v1/projects/{project['id']}/members",
        json={"email": "future3b@zerostrike.dev"},
        headers=_headers(owner),
    )

    attacker = register_and_login(client, email="future3b@zerostrike.dev")

    r = client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner))
    target = next(m for m in r.json() if m["invited_email"] == "future3b@zerostrike.dev")
    assert target["status"] == "pending"
    assert target["user_id"] is None

    assert client.get("/api/v1/projects", headers=_headers(attacker)).json()["total"] == 0


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


def test_demotion_race_guard_reverts_when_no_owner_left(client, monkeypatch):
    from app.models.project_member import ProjectMember

    owner = register_and_login(client, email="mowner11@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    owner_member_id = next(
        m["id"]
        for m in client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner)).json()
        if m["role"] == "owner"
    )

    # Simulate the race: the pre-check saw a second owner (which a concurrent request then demoted).
    real_find = ProjectMember.find
    calls = {"n": 0}

    class _Count:
        def __init__(self, n):
            self.n = n

        async def count(self):
            return self.n

    def fake_find(*a, **k):
        calls["n"] += 1
        return _Count(2) if calls["n"] == 1 else real_find(*a, **k)

    monkeypatch.setattr(ProjectMember, "find", fake_find)
    r = client.patch(
        f"/api/v1/projects/{project['id']}/members/{owner_member_id}",
        json={"role": "collaborator"},
        headers=_headers(owner),
    )
    assert r.status_code == 409
    monkeypatch.setattr(ProjectMember, "find", real_find)
    members = client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner)).json()
    assert [m["role"] for m in members] == ["owner"]


def test_invite_emails_point_existing_users_at_the_project_and_new_ones_at_register(client, sent):  # noqa: F811
    owner = register_and_login(client, email="mowner-mail@zerostrike.dev")
    register_and_login(client, email="has-account@zerostrike.dev")
    project = _create_project(client, _headers(owner), name="Mail Demo")
    for email in ("has-account@zerostrike.dev", "no-account@zerostrike.dev"):
        r = client.post(
            f"/api/v1/projects/{project['id']}/members", json={"email": email}, headers=_headers(owner)
        )
        assert r.status_code == 201

    by_to = {to: (subject, text) for to, subject, text, _ in sent}
    subject, text = by_to["has-account@zerostrike.dev"]
    assert "added you to Mail Demo" in subject and f"/projects/{project['id']}" in text
    subject, text = by_to["no-account@zerostrike.dev"]
    assert "invited you to Mail Demo" in subject and "/register?invite_token=" in text


def test_login_no_longer_silently_links_a_stuck_invite(client):
    """Login used to auto-link any pending invite matching the account's email by email alone --
    that's the same unverified-ownership gap as registration (see
    test_registration_without_token_does_not_claim_invite), just reachable one step later via an
    account that already existed when the invite was created without a token. It must stay
    pending until it is actually claimed with its token."""
    import asyncio
    from datetime import datetime, timezone

    from app.models.project_member import ProjectMember

    owner = register_and_login(client, email="mowner10@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    register_and_login(client, email="stuck10@zerostrike.dev")

    async def _stuck_invite():
        await ProjectMember(
            project_id=project["id"], invited_email="stuck10@zerostrike.dev",
            invited_by="x", invited_at=datetime.now(timezone.utc),
        ).insert()
    asyncio.run(_stuck_invite())

    r = client.post("/api/v1/auth/login", json={"email": "stuck10@zerostrike.dev", "password": "hunter2pass"})
    me = r.json()
    assert client.get("/api/v1/projects", headers=_headers(me)).json()["total"] == 0
    statuses = {m["invited_email"]: m["status"] for m in
                client.get(f"/api/v1/projects/{project['id']}/members", headers=_headers(owner)).json()}
    assert statuses["stuck10@zerostrike.dev"] == "pending"


def test_only_allowed_email_domains_can_register_or_be_invited(client, monkeypatch):
    from app.core.config import settings

    owner = register_and_login(client, email="mowner11@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    monkeypatch.setattr(settings, "signup_allowed_email_domains", ["thinkbridge.in", "thinkbridge.com"])

    def reg(email):
        return client.post("/api/v1/auth/register", json={"email": email, "password": "hunter2pass", "name": "U"})

    assert reg("someone@thinkbirgde.in").status_code == 422  # the prod typo
    assert reg("someone@gmail.com").status_code == 422
    assert reg("someone@thinkbridge.in").status_code == 201
    assert reg("other@ThinkBridge.com").status_code == 201

    invite = client.post(f"/api/v1/projects/{project['id']}/members",
                         json={"email": "x@thinkbirgde.in"}, headers=_headers(owner))
    assert invite.status_code == 422
    assert "@thinkbridge.in" in invite.json()["detail"]
    r = client.patch("/api/v1/users/me", json={"email": "mowner11@gmail.com"}, headers=_headers(owner))
    assert r.status_code == 422

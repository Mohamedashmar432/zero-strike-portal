"""User MCP over OAuth (docs/USER_MCP_OAUTH.md): discovery, registration, the PKCE flow, token
lifecycle, principal separation from the admin MCP, and the membership-scoped tools."""

import asyncio
import base64
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.config import settings
from app.models.audit_log import AuditLog
from app.models.finding import EvidenceEmbedded, Finding, LocationEmbedded, SecretEmbedded
from app.models.mcp_oauth import OAuthAuthorizationRequest, OAuthToken
from app.models.scan import Scan
from app.models.user import User
from app.models.vulnerability import Vulnerability
from app.services import audit_service
from tests.test_auth_flow import register_and_login
from tests.test_users import _promote_to_admin

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
REDIRECT = "http://127.0.0.1:53682/callback"
RESOURCE = settings.backend_public_url.rstrip("/") + "/mcp/user"
MISSING = "0" * 24


def _run(coro):
    return asyncio.run(coro)


def _jwt(client, email):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": "hunter2pass"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(client, email):
    register_and_login(client, email=email)
    return _jwt(client, email)


def _admin_user(client, email):
    register_and_login(client, email=email)
    _promote_to_admin(email)
    return _jwt(client, email)


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _register(client, redirect=REDIRECT, name="Test Client", method="client_secret_post"):
    r = client.post(
        "/register",
        json={
            "redirect_uris": [redirect],
            "client_name": name,
            "token_endpoint_auth_method": method,
            "scope": "mcp:read",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _authorize(client, reg, challenge, redirect=REDIRECT, resource=RESOURCE, **extra):
    params = {
        "response_type": "code",
        "client_id": reg["client_id"],
        "redirect_uri": redirect,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "st-1",
        "scope": "mcp:read",
        **({"resource": resource} if resource else {}),
        **extra,
    }
    return client.get("/authorize", params=params, follow_redirects=False)


def _request_id(authorize_response):
    assert authorize_response.status_code == 302, authorize_response.text
    loc = urlparse(authorize_response.headers["location"])
    assert loc.path == "/oauth/consent"
    return parse_qs(loc.query)["request"][0]


def _approve(client, headers, request_id):
    r = client.post(f"/api/v1/oauth/requests/{request_id}/approve", headers=headers)
    assert r.status_code == 200, r.text
    q = parse_qs(urlparse(r.json()["redirect_to"]).query)
    return q["code"][0], q["state"][0]


def _exchange(client, reg, code, verifier, redirect=REDIRECT):
    return client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": reg["client_id"],
            "client_secret": reg["client_secret"],
            "code_verifier": verifier,
        },
    )


def _refresh(client, reg, refresh_token, **extra):
    return client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": reg["client_id"],
            "client_secret": reg["client_secret"],
            **extra,
        },
    )


def _connect(client, headers):
    """The whole flow for the signed-in user; returns (client registration, token response)."""
    reg = _register(client)
    verifier, challenge = _pkce()
    rid = _request_id(_authorize(client, reg, challenge))
    code, _ = _approve(client, headers, rid)
    r = _exchange(client, reg, code, verifier)
    assert r.status_code == 200, r.text
    return reg, r.json()


def _rpc(client, token, method, params=None, path="/mcp/user"):
    headers = {**MCP_HEADERS, "Authorization": f"Bearer {token}"}
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post(path, json=body, headers=headers)


def _call(client, token, tool, **arguments):
    r = _rpc(client, token, "tools/call", {"name": tool, "arguments": arguments})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    if result.get("isError"):
        return {"__error__": result["content"][0]["text"]}
    return result["structuredContent"] if result.get("structuredContent") else json.loads(result["content"][0]["text"])


@pytest.fixture()
def owner(client):
    headers = _user(client, "owner@zerostrike.dev")
    _, tokens = _connect(client, headers)
    return headers, tokens["access_token"]


def _project(client, headers, name="Alpha"):
    r = client.post("/api/v1/projects", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


def _seed(project_id, kind="sast", evidence=None):
    async def _do():
        now = datetime.now(timezone.utc)
        scan = Scan(project_id=project_id, scan_type="cicd", status="completed", created_at=now, updated_at=now)
        await scan.insert()
        finding = Finding(
            scan_id=str(scan.id),
            project_id=project_id,
            fingerprint="fp-1",
            rule_id="R1",
            rule_name="Rule one",
            severity="high",
            message="Hardcoded thing",
            location=LocationEmbedded(file="src/app.py", start_line=3),
            kind=kind,
            evidence=[EvidenceEmbedded(snippet=evidence)] if evidence else [],
            secret=SecretEmbedded(detector_id="aws", redacted="AKIA************") if kind == "secret" else None,
            metadata={"match": "hunter2hunter2"} if kind == "secret" else {},
        )
        await finding.insert()
        await Vulnerability(
            project_id=project_id,
            repo_scope_key="unlinked",
            fingerprint="fp-1",
            current_severity="high",
            current_rule_id="R1",
            current_rule_name="Rule one",
            current_kind=kind,
            current_message="Hardcoded thing",
            current_location=LocationEmbedded(file="src/app.py", start_line=3),
            current_scan_id=str(scan.id),
            latest_finding_id=str(finding.id),
            first_seen_at=now,
            last_seen_at=now,
        ).insert()
        return str(scan.id), str(finding.id)

    return _run(_do())


def _audit_rows(action):
    return [a for a in _run(AuditLog.find_all().to_list()) if a.action == action]


# --- discovery ------------------------------------------------------------------------------


def test_discovery_documents(client):
    meta = client.get("/.well-known/oauth-authorization-server").json()
    assert meta["code_challenge_methods_supported"] == ["S256"]
    assert meta["scopes_supported"] == ["mcp:read"]
    paths = {urlparse(meta[k]).path for k in ("authorization_endpoint", "token_endpoint", "registration_endpoint", "revocation_endpoint")}
    assert paths == {"/authorize", "/token", "/register", "/revoke"}
    prm = client.get("/.well-known/oauth-protected-resource/mcp/user").json()
    assert prm["resource"].rstrip("/") == RESOURCE
    assert prm["authorization_servers"]


def test_unauthenticated_call_points_at_the_resource_metadata(client):
    r = client.post("/mcp/user", json={}, headers=MCP_HEADERS)
    assert r.status_code == 401
    assert 'resource_metadata="' in r.headers["www-authenticate"]
    assert "/.well-known/oauth-protected-resource/mcp/user" in r.headers["www-authenticate"]


def test_post_to_mcp_user_is_not_redirected_and_lists_the_nine_tools(client, owner):
    _, token = owner
    r = _rpc(client, token, "tools/list")
    assert r.status_code == 200 and r.history == []
    assert {t["name"] for t in r.json()["result"]["tools"]} == {
        "list_my_projects",
        "get_project_overview",
        "list_scans",
        "get_scan",
        "list_findings",
        "get_finding",
        "list_compliance_audits",
        "get_compliance_audit",
        "list_fix_proposals",
    }


# --- registration ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "uri",
    [
        "http://evil.example/cb",
        "javascript:alert(1)",
        "https://app.example/cb#frag",
        "ftp://x.example/cb",
        "https://u:p@app.example/cb",
    ],
)
def test_bad_redirect_uris_are_refused(client, uri):
    r = client.post("/register", json={"redirect_uris": [uri], "client_name": "x"})
    assert r.status_code == 400
    assert r.json()["error"] in ("invalid_redirect_uri", "invalid_client_metadata")


@pytest.mark.parametrize(
    "uri", ["https://claude.ai/api/mcp/auth_callback", "http://localhost:8123/cb", "http://[::1]:9/cb"]
)
def test_https_and_loopback_redirects_are_accepted(client, uri):
    assert client.post("/register", json={"redirect_uris": [uri], "client_name": "x"}).status_code == 201


def test_registration_is_rate_limited_per_ip(client):
    codes = [client.post("/register", json={"redirect_uris": [REDIRECT]}).status_code for _ in range(12)]
    assert codes[:10] == [201] * 10 and codes[10:] == [429, 429]


def test_registration_refuses_oversized_metadata(client):
    # Open registration is stored forever; one call must not be able to store megabytes.
    big_name = client.post("/register", json={"redirect_uris": [REDIRECT], "client_name": "x" * 101})
    big_extra = client.post("/register", json={"redirect_uris": [REDIRECT], "contacts": ["a@b.co"] * 1000})
    assert big_name.status_code == 400 and big_extra.status_code == 400


def test_authorize_is_rate_limited_and_caps_state(client):
    reg = _register(client)
    _, challenge = _pkce()
    oversized = _authorize(client, reg, challenge, state="s" * 513)
    assert "error=invalid_request" in oversized.headers.get("location", "")
    codes = [_authorize(client, reg, challenge).status_code for _ in range(30)]
    assert 429 in codes and codes[0] == 302


def test_unsupported_scope_cannot_be_registered(client):
    r = client.post("/register", json={"redirect_uris": [REDIRECT], "scope": "mcp:read admin"})
    assert r.status_code == 400


# --- authorize validation --------------------------------------------------------------------


def test_authorize_refuses_a_foreign_resource_a_weak_challenge_and_plain_pkce(client):
    reg = _register(client)
    _, challenge = _pkce()
    other = _authorize(client, reg, challenge, resource="https://other.example/mcp")
    assert parse_qs(urlparse(other.headers["location"]).query)["error"] == ["invalid_target"]
    weak = _authorize(client, reg, "short")
    assert parse_qs(urlparse(weak.headers["location"]).query)["error"] == ["invalid_request"]
    plain = _authorize(client, reg, challenge, code_challenge_method="plain")
    assert plain.status_code == 400 or "error" in parse_qs(urlparse(plain.headers["location"]).query)
    assert _run(OAuthAuthorizationRequest.find_all().count()) == 0


def test_redirect_uri_must_match_exactly_and_never_redirects(client):
    reg = _register(client)
    _, challenge = _pkce()
    for bad in (REDIRECT + "/", "http://127.0.0.1:53683/callback", REDIRECT + "?x=1"):
        # an error page, never a redirect to a URL the client did not register
        assert _authorize(client, reg, challenge, redirect=bad).status_code == 400, bad


# --- consent --------------------------------------------------------------------------------


def test_consent_requires_login_and_shows_the_redirect_host(client):
    headers = _user(client, "consent@zerostrike.dev")
    reg = _register(client, name="Looks Official")
    _, challenge = _pkce()
    rid = _request_id(_authorize(client, reg, challenge))
    assert client.get(f"/api/v1/oauth/requests/{rid}").status_code == 401
    assert client.post(f"/api/v1/oauth/requests/{rid}/approve").status_code == 401
    d = client.get(f"/api/v1/oauth/requests/{rid}", headers=headers).json()
    assert d["client_name"] == "Looks Official" and d["redirect_host"] == "127.0.0.1:53682"
    assert d["scopes"] == ["mcp:read"] and d["account_email"] == "consent@zerostrike.dev"
    assert _run(OAuthToken.find_all().count()) == 0  # looking is not approving


def test_approve_is_single_use_and_deny_returns_access_denied(client):
    headers = _user(client, "once@zerostrike.dev")
    reg = _register(client)
    _, challenge = _pkce()
    rid = _request_id(_authorize(client, reg, challenge))
    _approve(client, headers, rid)
    assert client.post(f"/api/v1/oauth/requests/{rid}/approve", headers=headers).status_code == 404
    assert client.post(f"/api/v1/oauth/requests/{rid}/deny", headers=headers).status_code == 404

    rid2 = _request_id(_authorize(client, reg, challenge))
    r = client.post(f"/api/v1/oauth/requests/{rid2}/deny", headers=headers)
    q = parse_qs(urlparse(r.json()["redirect_to"]).query)
    assert q["error"] == ["access_denied"] and q["state"] == ["st-1"] and "code" not in q
    assert client.post(f"/api/v1/oauth/requests/{rid2}/approve", headers=headers).status_code == 404
    assert _audit_rows("MCP app access denied")


def test_expired_pending_request_cannot_be_approved(client):
    headers = _user(client, "late@zerostrike.dev")
    reg = _register(client)
    _, challenge = _pkce()
    rid = _request_id(_authorize(client, reg, challenge))

    async def _expire():
        await OAuthAuthorizationRequest.find_one(OAuthAuthorizationRequest.request_id == rid).update(
            {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}}
        )

    _run(_expire())
    assert client.get(f"/api/v1/oauth/requests/{rid}", headers=headers).status_code == 404
    assert client.post(f"/api/v1/oauth/requests/{rid}/approve", headers=headers).status_code == 404


# --- the flow and token lifecycle ---------------------------------------------------------------


def test_full_flow_issues_hashed_bound_tokens(client):
    headers = _user(client, "flow@zerostrike.dev")
    _, tokens = _connect(client, headers)
    assert tokens["token_type"].lower() == "bearer" and tokens["expires_in"] == 3600
    assert tokens["access_token"].startswith("tsoa_") and tokens["refresh_token"].startswith("tsor_")
    stored = _run(OAuthToken.find_all().to_list())
    assert len(stored) == 2
    for t in stored:
        assert t.token_hash not in (tokens["access_token"], tokens["refresh_token"])
        assert t.resource == RESOURCE and t.scopes == ["mcp:read"]
    assert _call(client, tokens["access_token"], "list_my_projects") == {"items": [], "total": 0}
    assert _audit_rows("MCP app authorized")
    assert audit_service.classify("MCP app authorized", None) == "privilege"
    assert audit_service.classify("MCP app revoked", None) == "privilege"


def test_code_reuse_is_refused_and_revokes_what_it_minted(client):
    headers = _user(client, "reuse@zerostrike.dev")
    reg = _register(client)
    verifier, challenge = _pkce()
    code, _ = _approve(client, headers, _request_id(_authorize(client, reg, challenge)))
    first = _exchange(client, reg, code, verifier)
    assert first.status_code == 200
    again = _exchange(client, reg, code, verifier)
    assert again.status_code == 400 and again.json()["error"] == "invalid_grant"
    assert _rpc(client, first.json()["access_token"], "tools/list").status_code == 401


def test_wrong_code_verifier_is_refused(client):
    headers = _user(client, "pkce@zerostrike.dev")
    reg = _register(client)
    _, challenge = _pkce()
    code, _ = _approve(client, headers, _request_id(_authorize(client, reg, challenge)))
    r = _exchange(client, reg, code, secrets.token_urlsafe(48))
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert _run(OAuthToken.find_all().count()) == 0


def test_code_is_bound_to_its_client_and_redirect_uri(client):
    headers = _user(client, "bound@zerostrike.dev")
    reg, other = _register(client), _register(client)
    verifier, challenge = _pkce()
    code, _ = _approve(client, headers, _request_id(_authorize(client, reg, challenge)))
    assert _exchange(client, other, code, verifier).status_code == 400
    assert _exchange(client, reg, code, verifier, redirect="http://127.0.0.1:1/callback").status_code == 400
    assert _exchange(client, reg, code, verifier).status_code == 200  # still valid for the right caller


def test_refresh_rotates_and_reuse_revokes_the_grant(client):
    headers = _user(client, "rot@zerostrike.dev")
    reg, t1 = _connect(client, headers)
    r2 = _refresh(client, reg, t1["refresh_token"])
    assert r2.status_code == 200
    t2 = r2.json()
    assert t2["refresh_token"] != t1["refresh_token"] and t2["access_token"] != t1["access_token"]
    assert _rpc(client, t1["access_token"], "tools/list").status_code == 401  # rotated away
    assert _rpc(client, t2["access_token"], "tools/list").status_code == 200
    # the old refresh token comes back: theft, so the whole grant dies
    replay = _refresh(client, reg, t1["refresh_token"])
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    assert _rpc(client, t2["access_token"], "tools/list").status_code == 401
    assert _refresh(client, reg, t2["refresh_token"]).status_code == 400
    assert client.get("/api/v1/oauth/connected-apps", headers=headers).json() == []


def test_refresh_cannot_widen_scope_or_cross_clients(client):
    headers = _user(client, "scope@zerostrike.dev")
    reg, t1 = _connect(client, headers)
    assert _refresh(client, reg, t1["refresh_token"], scope="mcp:read admin").status_code == 400
    assert _refresh(client, _register(client), t1["refresh_token"]).status_code == 400


def test_expired_access_token_is_401(client, owner):
    _, token = owner

    async def _expire():
        await OAuthToken.find(OAuthToken.kind == "access").update(
            {"$set": {"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)}}
        )

    _run(_expire())
    r = _rpc(client, token, "tools/list")
    assert r.status_code == 401 and 'error="invalid_token"' in r.headers["www-authenticate"]


def test_token_for_another_resource_is_refused(client, owner):
    _, token = owner

    async def _rebind():
        await OAuthToken.find_all().update({"$set": {"resource": "https://other.example/mcp"}})

    _run(_rebind())
    assert _rpc(client, token, "tools/list").status_code == 401


def test_revoking_a_connected_app_kills_access_and_refresh(client):
    headers = _user(client, "revoke@zerostrike.dev")
    reg, tokens = _connect(client, headers)
    apps = client.get("/api/v1/oauth/connected-apps", headers=headers).json()
    assert len(apps) == 1 and apps[0]["redirect_host"] == "127.0.0.1:53682" and apps[0]["client_name"] == "Test Client"
    assert _rpc(client, tokens["access_token"], "tools/list").status_code == 200
    assert client.delete(f"/api/v1/oauth/connected-apps/{apps[0]['id']}", headers=headers).status_code == 204
    assert _rpc(client, tokens["access_token"], "tools/list").status_code == 401
    assert _refresh(client, reg, tokens["refresh_token"]).status_code == 400
    assert client.get("/api/v1/oauth/connected-apps", headers=headers).json() == []
    assert _audit_rows("MCP app revoked")


def test_a_user_can_only_see_and_revoke_their_own_grants(client):
    a = _user(client, "ga@zerostrike.dev")
    b = _user(client, "gb@zerostrike.dev")
    _connect(client, a)
    grant_id = client.get("/api/v1/oauth/connected-apps", headers=a).json()[0]["id"]
    assert client.get("/api/v1/oauth/connected-apps", headers=b).json() == []
    assert client.delete(f"/api/v1/oauth/connected-apps/{grant_id}", headers=b).status_code == 404
    assert client.delete("/api/v1/oauth/connected-apps/not-an-id", headers=b).status_code == 404
    assert len(client.get("/api/v1/oauth/connected-apps", headers=a).json()) == 1


def test_oauth_revoke_endpoint_ends_the_grant(client):
    headers = _user(client, "rfc7009@zerostrike.dev")
    reg, tokens = _connect(client, headers)
    r = client.post(
        "/revoke",
        data={"token": tokens["refresh_token"], "client_id": reg["client_id"], "client_secret": reg["client_secret"]},
    )
    assert r.status_code == 200
    assert _rpc(client, tokens["access_token"], "tools/list").status_code == 401


def test_deactivated_user_is_refused_at_once(client, owner):
    _, token = owner

    async def _deactivate():
        user = await User.find_one(User.email == "owner@zerostrike.dev")
        user.is_active = False
        await user.save()

    _run(_deactivate())
    assert _rpc(client, token, "tools/list").status_code == 403
    assert _audit_rows("MCP app access denied")


def test_deactivated_user_cannot_complete_the_exchange(client):
    headers = _user(client, "gone@zerostrike.dev")
    reg = _register(client)
    verifier, challenge = _pkce()
    code, _ = _approve(client, headers, _request_id(_authorize(client, reg, challenge)))

    async def _reject():
        user = await User.find_one(User.email == "gone@zerostrike.dev")
        user.approval_status = "rejected"
        await user.save()

    _run(_reject())
    assert _exchange(client, reg, code, verifier).status_code == 400


# --- principal separation -----------------------------------------------------------------------


def test_admin_token_oauth_token_and_jwt_do_not_cross_endpoints(client):
    admin_headers = _admin_user(client, "sepadmin@zerostrike.dev")
    r = client.post("/api/v1/admin/mcp-tokens", json={"label": "x", "expires_in_days": 30}, headers=admin_headers)
    admin_token = r.json()["raw_token"]
    _, tokens = _connect(client, admin_headers)
    oauth_token = tokens["access_token"]
    jwt = admin_headers["Authorization"].split()[1]

    assert _rpc(client, admin_token, "tools/list", path="/mcp/user").status_code == 401
    assert _rpc(client, oauth_token, "tools/list", path="/mcp").status_code == 401
    for path in ("/mcp/user", "/mcp"):
        assert _rpc(client, jwt, "tools/list", path=path).status_code == 401
    # sanity: each works on its own endpoint, and the portal API accepts neither as a bearer
    assert _rpc(client, admin_token, "tools/list", path="/mcp").status_code == 200
    assert _rpc(client, oauth_token, "tools/list", path="/mcp/user").status_code == 200
    bearer = {"Authorization": f"Bearer {oauth_token}"}
    assert client.get("/api/v1/projects", headers=bearer).status_code == 401
    assert client.get("/api/v1/oauth/connected-apps", headers=bearer).status_code == 401


# --- tools: membership, shaping, audit ---------------------------------------------------------


def test_member_sees_only_their_projects_and_non_members_get_not_found(client, owner):
    headers, token = owner
    mine = _project(client, headers, "Mine")
    stranger = _user(client, "stranger@zerostrike.dev")
    theirs = _project(client, stranger, "Theirs")
    scan_id, finding_id = _seed(theirs["id"])
    _seed(mine["id"])

    listed = _call(client, token, "list_my_projects")
    assert [p["name"] for p in listed["items"]] == ["Mine"] and listed["items"][0]["my_role"] == "owner"
    assert "open_findings_by_severity" in listed["items"][0]

    for tool in ("get_project_overview", "list_scans", "list_findings", "list_compliance_audits"):
        refused = _call(client, token, tool, project_id=theirs["id"])
        absent = _call(client, token, tool, project_id=MISSING)
        assert refused == absent and "not found" in refused["__error__"].lower(), tool
    for tool, arg, real in (
        ("get_scan", "scan_id", scan_id),
        ("get_finding", "finding_id", finding_id),
        ("list_fix_proposals", "scan_id", scan_id),
        ("get_compliance_audit", "audit_id", finding_id),
        ("list_findings", "scan_id", scan_id),
    ):
        refused = _call(client, token, tool, **{arg: real})
        assert refused == _call(client, token, tool, **{arg: MISSING}), tool
        assert "__error__" in refused


def test_membership_is_checked_per_call_so_removal_takes_effect(client, owner):
    headers, _ = owner
    project = _project(client, headers, "Shared")
    member_headers = _user(client, "member@zerostrike.dev")
    _, member_tokens = _connect(client, member_headers)
    member_token = member_tokens["access_token"]
    assert "__error__" in _call(client, member_token, "get_project_overview", project_id=project["id"])
    r = client.post(
        f"/api/v1/projects/{project['id']}/members", json={"email": "member@zerostrike.dev"}, headers=headers
    )
    assert r.status_code == 201, r.text
    assert _call(client, member_token, "get_project_overview", project_id=project["id"])["name"] == "Shared"
    client.delete(f"/api/v1/projects/{project['id']}/members/{r.json()['id']}", headers=headers)
    assert "__error__" in _call(client, member_token, "get_project_overview", project_id=project["id"])


def test_admin_sees_every_project_like_the_portal(client):
    admin_headers = _admin_user(client, "ua@zerostrike.dev")
    _, tokens = _connect(client, admin_headers)
    other = _user(client, "ub@zerostrike.dev")
    _project(client, other, "Someone elses")
    items = _call(client, tokens["access_token"], "list_my_projects")["items"]
    assert [p["name"] for p in items] == ["Someone elses"] and items[0]["my_role"] == "admin"


def test_tools_return_scans_findings_and_overview(client, owner):
    headers, token = owner
    project = _project(client, headers)
    scan_id, finding_id = _seed(project["id"])

    overview = _call(client, token, "get_project_overview", project_id=project["id"])
    assert overview["my_role"] == "owner" and len(overview["trend"]) == 1 and overview["repos"] == []
    scans = _call(client, token, "list_scans", project_id=project["id"], status="completed")
    assert scans["total"] == 1 and scans["items"][0]["id"] == scan_id
    assert _call(client, token, "list_scans", project_id=project["id"], status="failed")["items"] == []
    assert _call(client, token, "get_scan", scan_id=scan_id)["findings_by_severity"]["high"] == 1

    by_project = _call(client, token, "list_findings", project_id=project["id"], severity="high", file="app.py")
    assert by_project["items"][0]["finding_id"] == finding_id and by_project["items"][0]["status"] == "open"
    assert _call(client, token, "list_findings", project_id=project["id"], status="resolved")["items"] == []
    by_scan = _call(client, token, "list_findings", scan_id=scan_id, rule="R1")
    assert by_scan["items"][0]["id"] == finding_id
    assert "__error__" in _call(client, token, "list_findings")
    assert "__error__" in _call(client, token, "list_findings", scan_id=scan_id, project_id=project["id"])

    f = _call(client, token, "get_finding", finding_id=finding_id)
    assert f["location"]["file"] == "src/app.py" and f["triage"]["status"] == "open"
    assert _call(client, token, "list_fix_proposals", scan_id=scan_id)["items"] == []
    assert _call(client, token, "list_compliance_audits", project_id=project["id"])["items"] == []


def test_limits_default_and_cap(client, owner):
    headers, token = owner
    project = _project(client, headers)

    async def _many():
        now = datetime.now(timezone.utc)
        for _ in range(205):
            await Scan(project_id=project["id"], scan_type="cicd", created_at=now, updated_at=now).insert()

    _run(_many())
    assert len(_call(client, token, "list_scans", project_id=project["id"])["items"]) == 50
    assert len(_call(client, token, "list_scans", project_id=project["id"], limit=1000)["items"]) == 200


def test_secret_findings_reveal_no_more_than_the_masked_value(client, owner):
    headers, token = owner
    project = _project(client, headers)
    _, finding_id = _seed(project["id"], kind="secret", evidence="password = 'hunter2hunter2'")
    out = json.dumps(_call(client, token, "get_finding", finding_id=finding_id))
    assert "hunter2hunter2" not in out and "AKIA************" in out
    assert "hunter2hunter2" not in json.dumps(_call(client, token, "list_findings", project_id=project["id"]))


def test_tool_calls_are_audited_with_the_project_only_for_members(client, owner):
    headers, token = owner
    project = _project(client, headers)
    stranger = _user(client, "probe-target@zerostrike.dev")
    theirs = _project(client, stranger, "Theirs")
    _call(client, token, "get_project_overview", project_id=project["id"])
    _call(client, token, "get_project_overview", project_id=theirs["id"])
    _call(client, token, "list_my_projects")
    rows = _audit_rows("MCP tool called")
    mine = [r for r in rows if r.metadata["arguments"].get("project_id") == project["id"]][0]
    assert mine.project_id == project["id"] and mine.metadata["tool"] == "get_project_overview"
    assert mine.metadata["outcome"] == "ok" and "client_id" in mine.metadata
    probe = [r for r in rows if r.metadata["arguments"].get("project_id") == theirs["id"]][0]
    assert probe.project_id is None and probe.metadata["outcome"] == "refused"  # not written into their trail
    assert any(r.metadata["tool"] == "list_my_projects" for r in rows)
    assert all(r.actor_user_id for r in rows)

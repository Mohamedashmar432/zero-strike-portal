# User MCP over OAuth (SMCP, phase 2)

Status: planned 2026-10-19. Companion to `docs/ADMIN_MCP.md`, which stays as it is.

## Why

Any portal user should be able to connect an AI client to thinkShield by pasting one URL. Clients
that only take a URL (claude.ai and ChatGPT connectors, Claude Desktop's remote connectors)
cannot send a custom header, so a pasted `tsmcp_` token does not work for them. They speak the MCP
authorization spec: OAuth 2.1 with PKCE, dynamic client registration and discovery documents.
The portal becomes its own authorization server, and the user signs in and approves in the browser.

## Two endpoints, two principals, never shared

| | Admin MCP | User MCP |
| --- | --- | --- |
| URL | `/mcp` | `/mcp/user` |
| Credential | `tsmcp_` personal token, pasted as a header | OAuth access token, obtained by the client |
| Who | admins only, re-checked per request | any active, approved user |
| Data | portal-wide diagnostics | only projects the user is a member of (admins: all, as in the portal) |

An OAuth access token is refused on `/mcp`, and a `tsmcp_` token is refused on `/mcp/user`.
Neither is accepted by any `/api/v1` route, and no JWT is accepted on either MCP endpoint.

## OAuth design

Built on the `mcp` SDK's `OAuthAuthorizationServerProvider` protocol and auth routes. We implement
the provider over Mongo; the SDK handles request validation, PKCE checks and the response formats.

- **Issuer** is the backend's public origin (a setting; it must be HTTPS in prod, and loopback
  HTTP is allowed in dev). The SDK serves `/.well-known/oauth-authorization-server`, `/register`,
  `/authorize`, `/token` and `/revoke`. We serve `/.well-known/oauth-protected-resource/mcp/user`,
  and a 401 from `/mcp/user` carries `WWW-Authenticate: Bearer resource_metadata="…"` so clients
  can discover it.
- **Dynamic client registration** stores `OAuthClient` docs. It is rate-limited per IP. A
  `redirect_uri` must be `https://` or loopback `http://` (`127.0.0.1`, `localhost`, `[::1]`).
  The client name is display text only and is never trusted.
- **Authorize.** The SDK validates the client and `redirect_uri`, then `provider.authorize()` stores
  a pending `OAuthAuthorizationRequest` (10-minute TTL) and redirects the browser to the frontend
  consent page `/oauth/consent?request=<id>`. That page sits behind the normal login, so a
  signed-out user logs in and comes back. It shows the client name, the **redirect host**
  (prominent, because registration is open and the name can lie), the scope and the user's
  account. Nothing is auto-approved.
- **Approve or deny** goes through JWT-authenticated `POST /api/v1/oauth/requests/{id}/approve|deny`.
  - Approve is single-use. It mints an authorization code (5-minute TTL, single use, hashed,
    bound to user + client + `redirect_uri` + PKCE challenge + resource) and returns `redirect_to`,
    which the frontend navigates to.
  - Deny returns the `redirect_uri` with `error=access_denied`.
  - Both validate that the pending request has not expired or already been used.
- **Tokens.** The access token is opaque and random, lives 1 hour and is stored as a sha256 hash
  (prefix `tsoa_`). The refresh token lives 30 days, is **rotated on every use**, and reusing an
  old refresh token revokes the whole grant. Both are bound to user, client, scopes and resource
  (RFC 8707; a token for another resource is refused). Token docs carry a TTL index.
- **Scope** is a single `mcp:read`. All phase-2 tools are read-only.
- **Every request** re-checks that the user is active and approved. Project membership is checked
  **per tool call**, never baked into the token, so removing a member takes effect on the next call.
- **Connected apps.** A settings page `/settings/connected-apps` lists the user's grants (client
  name, redirect host, created, last used) and revokes them. Revoking kills both access and refresh
  tokens.
- **Audit:** `MCP app authorized`, `MCP app access denied`, `MCP app revoked` (the privilege bucket
  needs a marker — add `"mcp app"` to `_PRIVILEGE_MARKERS`), and `MCP tool called` with the
  project id.

## User tools (read-only, membership-scoped)

Each tool takes ids and returns at most what the portal's own API returns to that user, using the
same response shaping and redaction (secret-type findings must not reveal more than the
vulnerabilities page does). Lists default to 50 items, hard cap 200.

| Tool | Answers |
| --- | --- |
| `list_my_projects` | My projects: id, name, my role, last scan status/time, open findings by severity |
| `get_project_overview` | One project's posture: severity counts, trend of the last scans, repos |
| `list_scans` | Scans for a project, filter by status/type |
| `get_scan` | One scan: status, error message, timing, finding summary |
| `list_findings` | Findings for a project or scan, filter by severity, status, rule, file |
| `get_finding` | One finding with location, description, remediation and any AI insight |
| `list_compliance_audits` | Audits for a project with score and coverage |
| `get_compliance_audit` | One audit's control verdicts (failing first) |
| `list_fix_proposals` | Auto-fix proposals and PR status for a scan |

A non-member asking for a project, scan or finding gets the same "not found" as a missing id, so
ids cannot be probed.

## Testing

- **pytest:** discovery documents; registration validation (bad `redirect_uri` refused, rate
  limit); the full flow with a PKCE S256 code exchange; code reuse refused; a wrong
  `code_verifier` refused; refresh rotation plus reuse revoking the grant; expired access token
  401; a revoked grant 401; a deactivated user refused; a member sees only their projects; a
  non-member gets not-found; the admin token is refused on `/mcp/user` and an OAuth token on
  `/mcp`; tool calls audited.
- **Live:** the `mcp` SDK client's OAuth provider runs the real flow against :8001, with the
  consent approval done through the API using the user's JWT, then calls every tool.
- **Browser:** the consent page signed in and signed out; approve and deny; connected-apps revoke;
  member versus admin.
- `/security-audit` over both MCP surfaces before commit.

## Not in phase 2

Write tools, finer-grained scopes, per-project grants, and making admin diagnostics reachable over
OAuth.

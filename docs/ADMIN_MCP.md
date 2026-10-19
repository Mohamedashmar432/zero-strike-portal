# Admin MCP server (SMCP, phase 1)

Status: planned 2026-10-19. Scope of phase 1: **admin role only, read-only tools.**

## Why

Portal developers and admins debug the portal from an AI agent (Claude Code, Claude Desktop,
any MCP client) instead of clicking through Operations, Audit Log and System Logs. The agent
connects to the portal over MCP with a credential tied to one admin account and calls tools that
return the same data those admin pages show, shaped for diagnosis.

## Decisions

**Transport.** Streamable HTTP, mounted inside the existing FastAPI app at `/mcp`. Official
`mcp` Python SDK (`FastMCP`, `stateless_http=True`, `json_response=True`) — the protocol is not
something to hand-roll. No new process, no new container; the session manager is started in
`main.py`'s lifespan.

**Credential: a personal admin MCP token, not a JWT and not a project API key.** JWTs expire in
minutes and need a refresh dance an agent config cannot do; project `ApiKey`s are project-scoped
and belong to the scanner. New model `McpToken` (`mcp_tokens`): `user_id`, `label`, `prefix`,
`key_hash` (sha256 via `security.hash_token`, unique), `created_at`, `expires_at` (always set:
7, 30 or 90 days, default 30), `revoked_at`, `last_used_at`, `last_used_ip`. Raw token `tsmcp_<random>` is shown
exactly once at creation.

**Admin is re-checked on every request.** The token resolves to a `User`; the request is
refused unless that user is still `is_active`, `approval_status == "approved"` and
`role == "admin"`. Demoting or deactivating an admin kills their MCP access immediately, without
anyone remembering to revoke tokens.

**Auth lives in a thin ASGI wrapper around the mounted MCP app**, not the SDK's OAuth server.
It reads `Authorization: Bearer`, resolves the token, returns 401/403 JSON otherwise, and sets
a contextvar holding the admin user + token id for tool handlers. A third principal type: it
never yields to `get_current_user` or `get_api_key_context` handlers.

**Every tool call is audited** (`MCP tool called`, actor = the admin, metadata = tool name +
arguments, `admin` bucket). Token issue/revoke are `MCP credential issued/revoked` — the
`credential` marker puts them in the `privilege` bucket with no classifier change.

**Read-only in phase 1.** No tool mutates state. Reaping stuck jobs, retrying scans, toggling
settings are deliberate follow-ups once the read surface has been used.

**Output discipline.** Every list tool has a `limit` (default 50, hard cap 200); log messages
and tracebacks are truncated (message 2 000 chars, exception 8 000) and passed through
`secret_redaction.redact`. Runtime config is an explicit allow-list — never dump `settings`.
User data is minimal: no "list all users" tool; `lookup_user` takes an email or id and returns
role/status only.

**Kill switch.** `settings.mcp_enabled` (default `True`). When off, `/mcp` is not mounted.

## Tools (phase 1)

| Tool | Answers | Source |
| --- | --- | --- |
| `get_system_health` | Is the portal healthy right now? Mongo ping, scanner binary present, queue depths, CPU/memory, error count last hour | `cloud_scan_service.scanner_available`, `system_metrics.sample`, `SystemLog` count |
| `get_operations_overview` | What is queued/running in all four queues, avg run times, 24h failures | `operations_service.overview()` |
| `get_scanner_status` | Binary checklist, scanner queue, clone workspace state, recent scanner failures | `scanner_status_service.get_status()` |
| `list_system_logs` | Recent WARNING+ log lines, filter by `level`, `logger`, `contains`, `request_id`, `scan_id`, `since_minutes` | `SystemLog` |
| `get_system_log` | One log row with full (redacted) traceback and context | `SystemLog` |
| `summarize_errors` | Top error groups in a window: (logger, level, message head) → count, first/last seen, one sample id | `SystemLog` aggregate |
| `trace_request` | Everything one request touched: system logs + audit rows for a `request_id` | `SystemLog.context.request_id`, `AuditLog` |
| `list_audit_logs` | Who did what: `days`, `category`, `action_contains`, `actor_user_id`, `project_id`, `failures_only` | `AuditLog` + `audit_service.classify` |
| `inspect_job` | Full state of one job: `kind` ∈ cloud_scan / ai_analysis / remediation / compliance (the `operations_service.QUEUES` kinds), `id` → status, timestamps, error, project | the four job models |
| `list_failed_jobs` | Recent failures across all queues with error messages | operations/job models |
| `get_ai_health` | Portal-wide AI: calls, error rate by error type, latency, cost, plus recent failed `AIUsageEvent`s | `ai_analytics_service.get_analytics/list_events` |
| `get_runtime_config` | Allow-listed non-secret settings (timeouts, concurrency, scanner path, smtp configured y/n, byok on/off) + workspace settings | `settings`, `workspace_settings_service` |
| `get_data_stats` | Collection counts (optionally per project) | `data_management_service` |
| `list_projects` | id, name, member count, last scan status/time — so other tools' ids mean something | `Project`, `Scan` |
| `lookup_user` | One user by email or id: role, active, approval, created, last login. No list. | `User` |

## Surfaces

- Backend: `models/mcp_token.py`, `services/mcp_token_service.py`, `mcp/server.py` (FastMCP +
  tools), `mcp/auth.py` (ASGI wrapper + contextvar), `routers/admin_mcp_tokens.py`
  (`GET/POST/DELETE /api/v1/admin/mcp-tokens`, `require_admin`, a caller sees and revokes only
  their own tokens).
- Frontend: admin page `admin/mcp` — issue a token (label, expiry), copy-once reveal, list with
  last used, revoke, and a copyable client config snippet (`claude mcp add --transport http
  thinkshield <origin>/mcp --header "Authorization: Bearer …"`).

## Testing

- pytest: token issue/resolve/expire/revoke; non-admin token owner refused (403); demoted admin
  refused; missing/garbage token 401; each tool returns the expected shape over seeded mongomock
  data; secrets redacted in log output; tool call writes an audit row; `limit` capped.
- Live: start backend on :8001, connect with the `mcp` SDK client using a real token, list tools,
  call each one.
- Browser: admin issues/revokes a token on `admin/mcp`; member cannot reach the page or the API.

## Follow-ups (not phase 1)

Write tools (reap stuck jobs, retry a failed scan, cancel a queued job) behind a per-token
`allow_write` flag; project-member MCP scoped by membership; MCP resources/prompts.

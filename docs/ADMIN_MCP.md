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
User data is minimal: `lookup_user` and `list_users` return identity, role and status only, never
credentials.

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

## Full-portal read tools

Added 2026-11-03 so an admin's agent can look at everything the admin pages show, in particular the
Scan Engine and its noisy rules. Same rules as phase 1 (audited per call, `limit` capped at 200, text
clipped and run through `secret_redaction.redact`, `readOnlyHint`). They are registered through
`_safe_tool`, which additionally drops any key named `password`, `repo_token`, `refresh_tokens`, or ending in
`_hash` / `_enc` / `_encrypted` from the output, so a model field added later cannot leak through a
tool that forgot to allow-list it. Rows are allow-listed field by field in the first place. A secret-type
finding exposes its rule, location and masked value only (no message, snippet or scanner metadata), as the user MCP does.
Webhook URLs are never returned, only their host.

| Tool | Answers | Source |
| --- | --- | --- |
| `list_scan_rules` | Rules with finding counts, FP tags and rate; filter `query`, `state`, `noisy_only` | `scan_engine_service.rule_stats` |
| `list_noisy_rules` | Rules over the noisy threshold, worst first | `rule_stats` |
| `get_scan_rule` | One rule's stats, retire/custom state, who tagged which project's finding a false positive | `rule_stats`, `rule_fp_history`, `CustomRule` |
| `get_rule_pack` | Active pack, recent versions, pending (unpublished) changes, custom-rule metadata | `RulePackVersion`, `pending_changes` |
| `list_scans` / `get_scan` | Scans by project/status/type; one scan with stage, error, scanner version, CI fields, severity counts | `Scan` |
| `list_findings` / `get_finding` | A scan's raw findings; one finding with guidance and triage | `Finding` |
| `list_vulnerabilities` | Tracked vulnerabilities by project/severity/status/rule | `Vulnerability` |
| `list_finding_reviews` | The admin false-positive / accepted-risk queue | `finding_reviews._items` |
| `list_compliance_audits` / `get_compliance_audit` | Audits and one audit's control verdicts | `ComplianceAudit` |
| `list_fix_proposals` / `list_remediation_jobs` | Auto-fix proposals (no code) and propose/apply jobs | `AIFixProposal`, `RemediationJob` |
| `get_ai_usage` / `get_ai_budgets` | AI analytics portal-wide or per project; projects with budgets and month-to-date spend | `ai_analytics_service`, `ai_budget_service` |
| `list_users` | Users by role/approval status | `User` |
| `list_webhook_channels` | Channel name, host, events, project scope, last delivery status | `WebhookChannel` |
| `get_digest_status` / `get_live_alert_status` | Digest schedule and last send; live advisory watcher health | `digest_service`, `live_alert_service.status` |
| `get_project` | Full project config, overrides, and effective policies | `workspace_settings_service.effective_*` |
| `list_api_keys` | A project's key metadata (prefix, label, expiry, last used) | `ApiKey` |

## Not yet

No write tools. Each needs its own design behind a per-token `allow_write` flag: retiring/restoring
a rule, publishing or rolling back a rule pack, deciding a finding review, reaping or retrying jobs.

## Surfaces

- Backend: `models/mcp_token.py`, `services/mcp_token_service.py`, `mcp/server.py` (FastMCP +
  tools), `mcp/auth.py` (ASGI wrapper + contextvar), `routers/admin_mcp_tokens.py`
  (`GET/POST/PATCH/DELETE /api/v1/admin/mcp-tokens`, `require_admin`, a caller sees, renames and
  revokes only their own tokens).
- Frontend: Settings > Integrations > AI agents (`/settings/integrations/mcp`; `/admin/mcp` redirects
  there) — issue a token (label, expiry), copy-once reveal dialog, and per-row Edit (rename), Reissue
  (new secret, old one revoked) and Remove (revoke). The copyable client command uses `--scope user`:
  without it Claude Code files the server under the exact spelling of the current folder, so an editor
  that opens it as `c:\...` instead of `C:\...` never sees the server.

## Testing

- pytest: token issue/resolve/expire/revoke; non-admin token owner refused (403); demoted admin
  refused; missing/garbage token 401; each tool returns the expected shape over seeded mongomock
  data; secrets redacted in log output; tool call writes an audit row; `limit` capped.
- Live: start backend on :8001, connect with the `mcp` SDK client using a real token, list tools,
  call each one.
- Browser: admin issues/renames/reissues/revokes a token on `/settings/integrations/mcp`; member cannot reach the page or the API.

## Follow-ups (not phase 1)

Write tools (reap stuck jobs, retry a failed scan, cancel a queued job) behind a per-token
`allow_write` flag; project-member MCP scoped by membership; MCP resources/prompts.

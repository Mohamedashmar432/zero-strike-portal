# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

thinkShield Portal: a SaaS app (Next.js frontend + FastAPI backend + MongoDB) that
orchestrates scans from the **independent** thinkShield Go SAST scanner (sibling repo
`../zero-strike-code-scanner`). The scanner has its own release cadence and is never
code-imported here — the portal only invokes its compiled binary as a subprocess or
receives its JSON report over HTTP.

See `docs/ZeroStrike_Phase1_Architecture_and_Engineering_Plan.md` for the original Phase 1
design doc. Treat it as historical context, not ground truth — several details (filesystem
artifact storage, a `query/`/`providers/` frontend split) were superseded by what's
actually in the code (Mongo/GridFS storage, no `query`/`providers` dirs). When the doc and
the code disagree, the code wins.

## Development commands

**Backend** (`backend/`, FastAPI + MongoDB/Beanie, Python >=3.11):
```
cd backend
python -m venv .venv && ./.venv/Scripts/pip install -e ".[dev]"
cp .env.example .env                       # set MONGODB_URI to a real MongoDB instance
./.venv/Scripts/uvicorn app.main:app --reload
./.venv/Scripts/pytest                      # runs against mongomock — no real Mongo needed
./.venv/Scripts/pytest tests/test_scans.py -k test_name   # single test
./.venv/Scripts/ruff check .                # lint (line-length 110, py312)
```

**Frontend** (`frontend/`, Next.js 16 + Tailwind v4 + shadcn/ui):
```
cd frontend
npm install
cp .env.example .env.local
npm run dev
npm run build
npm run lint
```

**Run both**: backend on :8000 (`uvicorn ... --reload`), frontend on :3000 (`npm run dev`),
then open http://localhost:3000. For cloud scans to actually execute (not just queue), set
`SCANNER_BINARY_PATH` in `backend/.env` to a real built `zerostrike`/`zerostrike.exe` (e.g.
the one built in `../zero-strike-code-scanner`) — otherwise the scan fails with "executable
not found".

**Deployment**: single-VM Docker Compose (`deploy/`), MongoDB Atlas as the only external
managed service — `cd deploy && docker compose up -d` after filling in `.env` and
`secrets/{mongodb_uri,jwt_secret}.txt`.

## Backend architecture

Layered, one direction of dependency: `routers/` (HTTP) → `services/` (business logic) →
`models/` (Beanie `Document`s). `schemas/` holds Pydantic request/response DTOs, kept
separate from the Mongo documents in `models/`. `main.py: create_app()` wires routers,
CORS, and a `lifespan` that connects Mongo and starts the cloud-scan poll loop as a
background `asyncio.Task`.

**Two auth schemes that never share a handler** (`core/deps.py`):
- `get_current_user` / `require_admin` — JWT bearer, for portal users (browser).
- `get_api_key_context` — opaque API key bearer, for the Go scanner CLI/CI client. Yields
  an `ApiKeyContext` (project scope), never a `User`, so the two principal types can't be
  confused. Scanner-facing routes live in `routers/scanner_scans.py`; portal-facing
  equivalents in `routers/scans.py` — deliberately split so a handler can't accidentally
  accept both.

**Project invites require a claim token, not just a matching email**
(`services/auth_service.py: link_pending_invites`, `models/project_member.py`): registering with
an allowed-domain address is not proof of mailbox ownership, so a pending `ProjectMember` (no
`user_id` yet) is only linked to a new account when the registrant presents the one-time token
from the invite email (`invite_token_hash`, sha256 via `security.generate_reset_token`/
`hash_token`, same pattern as password reset) — matching on `invited_email` alone would let
anyone register first with a victim's address and steal their pending invites. An invite that
resolved to an *existing* user at invite time carries no token and needs no claim; login no
longer auto-links pending invites by email either, for the same reason.

**Scan lifecycle** (`models/scan.py: ScanStatus`, `scan_type: cloud|cicd`):
- `cicd` scans are created *by the scanner itself* via API key (there is no `local` type any more —
  every scanner upload came from a pipeline, and a startup migration in `main.py` rewrites old rows)
  (`POST /api/v1/scans` in `scanner_scans.py`, status starts `pending`), which later
  `PUT .../status` and uploads its JSON/HTML report.
- `cloud` scans are created by the portal (`routers/scans.py: create_scan`, status starts
  `queued`) and run server-side — the portal owns the whole clone+scan+ingest pipeline.

**Cloud scan pipeline** — no new infra (no Redis/Celery/RabbitMQ), just Mongo + asyncio:
1. `scan_queue_service.py` — a Mongo-backed queue. `drain_queue()` atomically claims the
   oldest `queued` scan via `find_one_and_update` (safe across concurrent backend
   replicas) up to `max_concurrent_cloud_scans`, and hands it to `cloud_scan_service`. A
   `poll_loop()` (interval `queue_poll_interval_seconds`) also reaps scans stuck `running`
   past `scan_timeout_seconds * queue_stuck_multiplier` (crash recovery).
2. `cloud_scan_service.py` — SSRF-validates `repo_url` (rejects loopback/private/
   link-local/metadata IPs), `git clone --depth 1` with the repo token injected via
   `GIT_CONFIG_*` env vars (never argv/URL, so it can't leak into `ps`/logs), then runs
   `settings.scanner_binary_path scan <workdir> --format json --enable-secrets
   --enable-sca --enable-framework-checks` as a subprocess (`subprocess.run` in a worker
   thread — works identically on Windows dev and Linux prod, unlike
   `asyncio.create_subprocess_exec`). Exit codes 0 (clean) and 1 (findings) are both
   success.
3. `report_ingestion_service.ingest()` — the single place a Go scanner report becomes
   portal `Finding`/`Report` documents. Shared by the cloud path and the scanner's own
   `POST /scans/{id}/upload/json`. Idempotent (replaces any prior Finding/Report docs for
   that `scan_id`), stores the raw report JSON directly on the `Report` doc (no filesystem
   artifacts anywhere in this stack), marks the scan `completed`, and re-triggers
   `scan_queue_service.drain_queue()` to backfill the concurrency slot it just freed.

**AI provider resolution + usage log** (`docs/AI_BYOK_AND_ANALYTICS.md`): `AIProviderConfig` is
scoped by `project_id` — `None` is the portal-wide admin-managed provider, a set value is that
project's own key ("Project BYOK", toggled workspace-wide via
`WorkspaceSettings.project_byok_enabled`). `ai_provider_config_service.resolve_failover_configs()`
is the single place that policy is decided; with BYOK on a project runs *only* on its own key and
never falls back to the portal's. Every LLM call — success or failure — writes one `AIUsageEvent`
(feature, latency, tokens, cost, error type; **never** prompt/response content, 180-day TTL), read
back by `ai_analytics_service` at two scopes: per-project (`/projects/{id}/ai-analytics`,
member-gated) and portal-wide (`/admin/ai-analytics`, admin-gated). Rows also carry `job_id`/`finding_id`
(set by `llm_client.call_scope`, never per caller) and `cached_prompt_tokens`, which `ai_quality_service`
(`/admin/ai-analytics/quality`) turns into Auto-Fix acceptance, re-scan and per-finding cost/cache rates. AI
analysis groups findings by (rule, path class): a false-positive verdict on test/fixture code must never
transfer to the same rule in application code, and the model is sent the redacted snippet, not just a locator.

**AI cost and budgets** (`services/pricing_service.py`, `services/ai_budget_service.py`; see
`docs/AI_PRICING_AND_BUDGETS.md`): tokens come from the provider's `usage` block; cost is a
provider config's `input/output_cost_per_million` override, else litellm's price map (re-downloaded
daily), else **unknown** — `AIUsageEvent.cost_known=False`, never a silent `$0`. A failed download
must not merge litellm's bundled fallback over newer prices. Project budgets (monthly USD/tokens,
owner/admin-set) email the project **owner** once per (month, metric, threshold) via an atomic
`$addToSet` claim; `hard_stop` is checked in `llm_client` *before* any provider call.

**Compliance audits** (`core/compliance_catalog.py`, `services/compliance_audit_service.py`;
see `docs/CORE_FEATURE_GAP_HARDENING.md`): a deterministic evaluator maps scanner findings to
framework controls. `evaluate()` is pure — no Mongo, no LLM — and is the *only* thing that sets a
control's status; the optional LLM narrator writes advisory prose for already-failing controls and
can never move a verdict. Three rules that must not be softened: a control with no selector is
`needs_manual_review` (never `pass`), `compliance_score` is scored over code-assessable controls
only so it is **not** a compliance percentage (`coverage_percent` and the audit's repo counts exist
to keep that visible), and an audit with no scans in scope is refused rather than rendered as
all-pass. **Only `soc2` and `iso27001` are runnable** — `SUPPORTED_FRAMEWORK_KEYS`; the other four
frameworks stay in the catalog so historical audits render, but are not offered and are rejected at
trigger time. Widening that set means reviewing a framework's evidence mapping control-by-control
first, and a test asserts the current set.

**Config precedence — workspace defaults vs project overrides**
(`services/workspace_settings_service.py`; see `docs/CONFIG_SURFACE_WIRING.md`): `WorkspaceSettings`
is a singleton of portal-wide defaults; `Project` carries a nullable twin for every field a project
may override, where `None` means *inherit* (never "off"). `workspace_settings_service` is the sole
owner of the singleton and holds every `effective_*` resolver — no call site re-derives precedence.
The rule that must not be softened: **a project override may only tighten, never loosen.** A project
can disable auto-fix but cannot enable it against a workspace-wide disable, and can raise the
confidence threshold but never lower it below the workspace floor — enforced in
`effective_remediation_policy`, not at write time, so a later workspace change cannot silently
un-tighten a project. Spend-bearing policy (`auto_fix_findings_per_scan`, `blocking_severities`,
`max_findings_per_job`, `compliance_audit_ai_narrative`, quota grants) has no project twin at all
and stays under `require_admin`. Use `workspace_settings_service.load_project(id)` rather than
`Project.get(id)` — the latter raises on a malformed id instead of returning `None`.

**Auto-Fix: listing is the scan, execution is a batch** (`routers/ai_remediation.py:
trigger_scan_auto_fix`). Three separate limits, and conflating any two of them is the bug that
shipped once already: `max_findings_per_job` bounds **one run**, `auto_fix_findings_per_scan` (+
grants) bounds **the scan's total spend**, and **neither bounds what the UI lists** — the workspace
always shows every finding, with `AutoFixSummary.uncovered_findings` naming what is left. The
trigger therefore selects only findings that have *no proposal yet* (unless `force`): selecting
already-proposed ones refills every batch with finished work, so repeated clicks could never reach
past the top `max_findings_per_job` findings of a large scan — a 137-finding scan sat at 10
proposals forever. No button may promise "all", because no single run can deliver it;
`test_repeated_runs_advance_through_a_scan_larger_than_one_batch` locks the advance in.

**Auto-Fix: proposal granularity is not PR granularity** (`docs/AUTOFIX_BATCH_PR.md`). One approve
job writes ONE branch and ONE PR for a batch of proposals — `RemediationJob.proposal_ids`, with the
job itself acting as the batch entity (there is no `remediation_batch` collection, and adding one
means the batch needs to outlive its job). A batch is scoped to a single `scan_id`; that is what
makes it safe, because a scan has exactly one repo and one base branch by construction, so no
grouping engine re-derives those. Patch conflict is the one thing metadata can't predict, so it
isn't predicted: `ai_remediation_apply_service` applies, re-scans once over the combined diff,
**drops** whatever failed (a drifted source, a target that didn't clear, a patch blamed for a new
blocking finding), retries the survivors exactly once, and ships them. A new blocking finding in a
file no patch touched is unattributable and aborts the whole batch rather than guessing. Both
approve routes go through `routers/ai_remediation.py: _enqueue_apply` — the single-proposal route is
a batch of one — so approval semantics cannot drift. Every drop is recorded in the PR body's summary
table: a fix left out silently is the same auditability hole as a PR per finding, only quieter.

An audit's shape is configuration, not a per-run question: every field on
`POST /projects/{id}/compliance-audits` is optional, and an empty body (what the Run Audit button
sends) resolves frameworks, evidence scope and depth from `effective_compliance_policy`. The
three-step wizard that used to ask them is gone. A *configured* narrative preference downgrades to
deterministic when no AI provider is active — the verdicts are identical either way — while an
explicit `depth: "with_ai_narrative"` still 409s.

**Finding review: admin-accepted CI exemptions** (`services/finding_review_service.py`,
`routers/finding_reviews.py`; see `docs/FINDING_REVIEW.md`): a member's false positive (code
findings only) or accepted risk (any finding kind; comment of 40+ chars, `validate_risk_comment`) is a *request*
on `Vulnerability.review`. Whether it needs an admin is a per-kind workspace toggle, both admin-only, no project
twin, default **off**: `finding_review_required` for false positives, `risk_acceptance_review_required` for accepted
risk. Off, `request_review` accepts it immediately ("Auto-accepted: admin review is off", audit
`Finding Review Auto-Accepted`) through the same `_apply_acceptance` helper `decide` uses; on, it changes nothing
until a portal admin accepts it. Flipping a flag never touches pending or accepted rows. An admin can revoke either
way, and a finding with an accepted review cannot be reopened by status change (409) until revoked. Approval
notifies the requester in-app only, never by email.
**Risk acknowledgement** (`services/risk_acknowledgement_service.py`, `routers/risk_acknowledgements.py`; see
`docs/RISK_ACCEPT_REVIEW_AND_VULN_REDESIGN.md`): an admin, never automatically, can email the project owner plus up
to 10 extra addresses a PDF/CSV of the accepted risks. A `RiskAcknowledgementBatch` snapshots the findings; the
recipient token is sha256-hashed, single-use, travels in the URL fragment, and the awaited send records a real
per-recipient `delivery` (`not_configured` when `smtp_host` is unset; the UI says "sent" only for `sent`). An
acknowledgement counts only while the review's `reviewed_at` is unchanged, so revoke-and-reaccept supersedes it.
`accepted_exemptions()` is the single source for both portal suppression on ingest and the scanner's
create-scan response, so the portal and the CI gate cannot disagree. Two rules must not be softened:
an exemption matches **fingerprint AND repo-relative file** (the fingerprint has no path, so
fingerprint-only would silence the same snippet in other files), and the scanner nests exempted
findings under `AcceptedExemptions[].Finding` because customers' unchanged YAML gates grep
`^      "Severity"` at exactly six spaces. The scanner's `TestReportLayoutContract` locks that.

**Audit log** (`services/audit_service.py`, `routers/audit_logs.py`): `record()` is the only
writer and rows are immutable, so all read-side shaping happens on the way out.
`classify(action, project_id)` buckets a row as `privilege` (sign-ins, roles, members, API keys,
credentials), `project` (scoped to a project) or `admin` (portal-wide) — privilege wins over the
other two so an access change inside a project isn't buried in scan traffic. It matches the action
*name* rather than reading a stored field, deliberately: a stored category would only classify rows
written after it shipped. `GET /audit-logs` takes `days` (default 1) and `category`, and returns
per-category counts over the whole window next to the page — counts describe the window, never the
filtered slice. An explicit `since`/`until` range (the page's date pickers, sent as the admin's local
midnights) overrides `days` and is capped at 92 days. There is no pager yet; the page states how many
events it dropped rather than letting a truncated list read as the whole day. Separately,
`core/log_sink.py` persists every backend log record at WARNING+ to `system_logs` (90-day TTL),
served by `GET /audit-logs/system` as the page's "System logs" tab; `emit()` only enqueues, and a
lifespan task batches the inserts, so logging never blocks or fails a request.

**Notifications** (`core/notification_events.py`, `services/notification_service.py`): every
subscribable event is declared once in `EVENTS`, and `notify()` refuses a key that is not in it, so
the preferences UI and the emission sites cannot drift. `audience` gates delivery before per-user
preference: `"project"` reaches project members, `"admin"` reaches portal admins only. Preference is
per *user* (`User.notify_in_app` / `notify_email`), where `None` means "never chose" and resolves to
catalog defaults while `[]` means a deliberate opt-out — do not collapse the two. `notify()` never
raises: the scan, audit or fix that triggered it must complete whether or not anyone could be told.
Emission sites sit alongside existing `audit_service.record` calls. Email routes through
`email_service`, which no-ops while `smtp_host` is unset (the default everywhere today) — the
notifications page says so rather than implying mail is going out.

**Operations: queue positions and load** (`services/operations_service.py`, `services/system_metrics.py`;
see `docs/OPERATIONS_AND_QUEUEING.md`): a read-only view over all four queues (cloud scan, AI analysis,
auto-fix, compliance). It never claims or changes a job. `estimate_starts()` is the pure function behind every
"starts in ~m:ss" countdown, from each queue's recent average run (runs under 1s ignored, a fixed default
until 3 real ones exist). Two surfaces: `GET /queue` (the caller's projects, all for an admin; feeds the
"QUEUED · #2 · 1:23" tag that `ScanStatusBadge scanId=…` / `AiStatusBadge refId=…` render anywhere a job
can be queued — pass the id on any new list) and `GET /admin/operations` (admins; plus cgroup-v2
CPU/memory and 24h failures). Every queue's `drain_queue()` holds `job_queue.drain_lock(name)`: capacity-read-then-claim
raced between the poll loop and job completion and overshot the cap. The lock is per-process, which is exact
on the single replica we run.

**Webhook channels, digest, user activity** (`services/webhook_channel_service.py`, `services/digest_service.py`, `services/activity_service.py`, `services/pipeline_alert_service.py`, `services/error_alert_service.py`; see `docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md` Part 2): a `WebhookChannel` is a named, encrypted Teams URL (only its host is ever returned) subscribed to event keys and optionally to a project list. Routing lives in one place, `notification_service.notify()`, which posts to every matching enabled channel in a background task and never raises; a delivery failure is recorded on the channel and logged at **WARNING only**, because ERROR is what `portal.error` alerts on and an alert must not alert about itself. The old single `WorkspaceSettings.alert_webhook_enc` is migrated at startup (idempotent) to an "Admin alerts" channel; while that channel exists `alert_service.send_global` stands down so nothing double-posts, and the legacy settings page syncs into it. New events (`scanner.download_failed`, `pipeline.upload_stalled`, `pipeline.silent`, `portal.error`; `scan.failed` now carries stage/repo/branch/CI link as card facts) dedupe through `core/dedupe.py` -- an in-memory TTL gate, so a restart or second replica re-alerts once; stalled scans dedupe durably via an atomic `Scan.stalled_alerted_at` claim. The stalled/silent checks ride the scan queue's `poll_loop`, not a new task. The digest (`DigestSettings` singleton) is a pure card builder (`build_cards`, Adaptive Card 1.4, no `Table`) over `build_preview`, and it is **several cards, not one**: a scanner card (versions, new-CVE count, and the period's CI/CD scans on a scanner older than the latest published binary), project status 10 per card, then a three-KPI summary, posted in order with a gap (`_post_cards`), because Teams drops a message over ~28 KB and a Workflows webhook returns 202 before it fails (`RequestEntityTooLarge`), so an oversize card looks sent (see `docs/PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md` 6a); Critical/High are current exposure (`project_stats_service`), never summed scans, and the new-CVE figure is a count of advisory ids first seen in the period -- there is no local CVE feed to date. A channel with `include_digest` *and* a project list gets one card per project instead of the global digest, so a project's channel never sees other projects' numbers (see `docs/DIGEST_V2_AND_DEV_ALERTS.md`). `portal.error` reaches developers for unhandled exceptions (`main.py` catch-all handler), SMTP failures (`email_service`, ERROR), and an unreachable Mongo (`scan_queue_service.check_database`); `webhook_channel_service.route` falls back to the last loaded channel list for `portal.error` when Mongo is down. `scheduler_loop` wakes each minute and claims the period with one `find_one_and_update` on `last_sent_for`, so it cannot double-send; a slot missed by more than 6 hours is skipped rather than sent late. User activity is first-party: `user_activity_days` (unique user+day, 400-day TTL) is upserted from `get_current_user` and from `project_service.require_member`, throttled by an in-process seen-set and never raising; a portal admin viewing a project they are not a member of is **not** counted as one of its users. Tests stub every webhook post in `conftest.py` -- no test may reach the network.

**Live dependency advisory alerts** (`services/live_alert_service.py`, `core/advisory.py`, `services/advisory_feed_service.py`, `services/dependency_inventory_service.py`; see `docs/LIVE_DEPENDENCY_ALERTS.md`): when an advisory is *published* within the last 72 h and a package it affects is in a project's dependency inventory, that project is alerted once. The inventory is the scanner's top-level `Dependencies` report array (absent from older scanners and from runs without `--enable-sca`: absent means "no information" and leaves the previous snapshot alone, `[]` means a real empty inventory), stored one `DependencyInventory` per (project, repo scope) and replaced every scan; `ingest()` strips `Dependencies` from the stored raw report so the list is kept once. Its `direct` flag is raw data only and is never shown (the scanner's parsers mark nearly everything direct). "New" comes from OSV's per-ecosystem GCS `modified_id.csv` read with Range requests plus a per-ecosystem cursor, never from a per-package poll; candidates are confirmed by OSV's own matcher (`querybatch`, only package/version triples) unless the record lists the version. Rules that must not be softened: the first run never backfills (cursor starts at the feed head, and re-enabling resets it); a failed fetch or confirm leaves the cursor and retries (the ledger's unique `(project, ecosystem, package, version, advisory)` index makes a retry harmless) and never alerts a project; claim-then-deliver means at most once; a finding a scan already reported or an admin-accepted exemption suppresses the alert; a project may only tighten the severity threshold (`effective_live_alert_policy`). One run at a time via an atomic lease on the `AdvisoryWatchState` singleton (all state writes conditioned on `lease_owner`), driven by its own `watch_loop`. Delivery is one grouped message per project through `notify("dependency.new_advisory")` plus `alert_service.send_project_live_alert` (the project's own webhook and mailboxes); the email outcome is `not_configured` when `smtp_host` is unset and the UI never says "sent" unless it was. The feed hosts are fixed: `advisory_feed_base_url`/`osv_api_base_url` may only be overridden when `app_env == "development"`. No Finding or Vulnerability is created by an alert.

**Admin MCP server** (`mcp/`, `services/mcp_token_service.py`; see `docs/ADMIN_MCP.md`): `/mcp` serves 37 read-only tools (15 diagnostic: logs, queues, audit trail, jobs, AI health, allow-listed config; 22 full-portal: Scan Engine rules/noisy rules/rule pack, scans, findings, vulnerabilities, review queue, compliance, auto-fix, AI usage/budgets, users, webhook channels, digest, live alerts, project config, API key metadata; the new ones run through `_safe_tool`, which strips credential-shaped keys) to an AI agent over streamable HTTP, via the official `mcp` SDK. It is a third principal type beside the JWT user and the scanner API key: a personal `tsmcp_` token (`McpToken`, sha256-hashed, max 90 days, issued at `/admin/mcp-tokens`) resolved by `mcp/auth.py`, which re-checks the owner is an active, approved **admin on every request** so demoting an admin ends their access at once. Every tool call writes an `MCP tool called` audit row (fail-closed), outputs are truncated and passed through `secret_redaction.redact`, and `limit` caps at 200. No tool mutates state; a write tool needs its own design (per-token flag). `settings.mcp_enabled=False` leaves `/mcp` unmounted. Mounted as a plain `Route`, not a `Mount`, because a Mount 307-redirects `POST /mcp` to `/mcp/`. **User MCP** (`mcp/user_server.py`, `services/mcp_oauth_service.py`, `routers/oauth_consent.py`; see `docs/USER_MCP_OAUTH.md`): `/mcp/user` serves 9 read-only, membership-scoped tools plus one write tool, `mark_false_positive` (registered separately with `readOnlyHint=False`; it calls `finding_review_service.request_review`, so the review toggle applies, and refuses dependency findings), to any active, approved user whose AI client connected over OAuth 2.1 (PKCE S256, dynamic registration, discovery documents at the backend root, built by the `mcp` SDK's auth routes over a Mongo provider). Membership is checked per tool call, never baked into the token; a non-member gets the same "not found" as a missing id, and secret-type findings expose only the masked value. The two MCP credentials never cross: `tsmcp_` tokens are refused on `/mcp/user` and `tsoa_` access tokens on `/mcp`; tokens are bound to the `/mcp/user` resource, refresh tokens rotate with reuse revoking the grant, and users revoke grants under Settings > Connected Apps.

**Scanner binary distribution** (self-hosted, so bootstrapping a CI runner needs no
portal credentials): `download_service.py` + `models/scanner_binary.py` store built
`zerostrike` binaries in MongoDB GridFS (bucket `scanner_binaries`); `routers/downloads.py`
serves them publicly at `/api/v1/downloads/zerostrike/{version}/{os}-{arch}` and a
`checksums.txt`; `routers/admin_downloads.py` is the admin-only publish endpoint.
`version="latest"` resolves by `uploaded_at`, not semver parsing.

**Docker note**: `backend/Dockerfile` builds the Go scanner binary in a `golang` stage with
`CGO_ENABLED=1` (mandatory — a CGO-disabled build registers zero tree-sitter parsers and
silently finds nothing) and bakes it into the backend image; there's a build-time smoke
check that fails the build if the scanner stops detecting a known-vulnerable fixture. At
*scan* time there's no Docker involved — the backend just shells out to that baked-in
binary (or whatever `SCANNER_BINARY_PATH` points at locally).

**Tests** run against `mongomock_motor` (`AsyncMongoMockClient` monkeypatched over
`AsyncIOMotorClient` in `tests/conftest.py`) — no real MongoDB needed. Tests touching
GridFS (downloads) need `enabled_gridfs_integration()`.

## Frontend architecture

Next.js 16 App Router, route groups `(auth)` (login/register) and `(dashboard)` (sidebar
shell, guarded). TanStack Query for server state, `react-hook-form` + `zod` for forms,
shadcn/ui (Tailwind v4) for components.

- `lib/api/client.ts` — the single `fetch` wrapper: attaches the bearer access token,
  and on a 401 transparently calls `tryRefresh()` once and retries before giving up.
- `lib/api/token-store.ts` — access token is **in-memory only**; refresh token lives in
  `sessionStorage` (tab-scoped, survives reload, cleared on tab close by design).
- `lib/api/*.ts` — one file per backend resource (scans, projects, api-keys, findings,
  reports, ...), thin wrappers over `apiFetch`.
- `lib/validation/*.schema.ts` — zod schemas shared between forms and (implicitly) the
  API contract.

**Read `frontend/AGENTS.md` before writing Next.js-specific code** — it flags that this
Next.js version (16.2.10) has breaking API/convention changes vs. what's in most training
data; check `node_modules/next/dist/docs/` rather than assuming.

## Definition of done — Notion tracker is updated

After every fix, change, feature or issue found, invoke the `notion-tracker` skill: it adds the
commit to the Change Log and creates or updates the linked ticket (Status `Done` once shipped,
`Backlog` for issues found but not fixed). A post-commit hook reminds you, but the rule holds
without it (for example when a commit is made outside this session). Never put secrets or
`.env` values in Notion.

## Definition of done — browser QA is not optional

Unit tests, `tsc` and `ruff` are the *entry* gate, not the finish line. **Every change to a
user-facing surface gets a browser pass before it is called done.** The two defects that
shipped past a green suite on 2026-08-28 were both invisible to unit tests: the audit trail
recorded background-worker rows as `actor_type="user"` (so the log claimed a person did what
no person did), and the log linked project names that resolve to deleted projects, giving a
link that can only 404.

Order matters — the first two steps are where most "it doesn't work" reports actually come
from:

1. **Restart the backend and confirm the new code is live.** `uvicorn app.main:app --port
   8001` here is started *without* `--reload`, so it serves whatever it loaded at boot.
   Confirm by grepping `/openapi.json` for a field you just added — never by assuming.
   Windows also leaves orphaned `--reload` workers holding the port; see the memory note.
2. **Check the port.** Frontend `.env.local` points at **:8001**. A backend on :8000 makes
   every call fail in a way that looks like a code bug.
3. **Do not `npm run build` while `npm run dev` is running** — it corrupts `.next` and the
   dev server then serves stale CSS/JS silently. Type-check and lint instead.
4. **Drive the real UI** with the `chrome-devtools` MCP (setup gotchas are in the memory
   note — Chrome refuses remote debugging on the default profile). Prefer
   `take_snapshot`/`evaluate_script` over screenshots; a full snapshot of a long table is
   enormous, so read what you need with `evaluate_script`.
5. **Test both roles.** Most admin surfaces are `require_admin` and most project surfaces
   gate on membership; a member-only session silently hides half the product. Register a
   throwaway QA account and promote it the way `tests/test_users.py::_promote_to_admin`
   does. Keep its credentials in the scratchpad, never in the repo.
6. **Assert on the wire, not just the pixels.** Confirm the request body and status
   (`get_network_request`), not only that the page looks right — that is how "Run Audit
   posts `{}`" got verified.
7. **Exercise the refusal paths too.** A 409 that renders as a readable toast is a feature;
   an unhandled one is a dead button.
8. **Finish with `list_console_messages` and `list_network_requests`.** Zero errors and no
   unexpected non-2xx.
9. **Re-run the suite after fixing anything the browser found**, then record what the pass
   caught — a QA pass that found nothing and one that was never run look identical later.

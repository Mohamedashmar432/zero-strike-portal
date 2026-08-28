# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

ZeroStrike Portal: a SaaS app (Next.js frontend + FastAPI backend + MongoDB) that
orchestrates scans from the **independent** ZeroStrike Go SAST scanner (sibling repo
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

**Scan lifecycle** (`models/scan.py: ScanStatus`, `scan_type: local|cloud|cicd`):
- `local`/`cicd` scans are created *by the scanner itself* via API key
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
member-gated) and portal-wide (`/admin/ai-analytics`, admin-gated).

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

An audit's shape is configuration, not a per-run question: every field on
`POST /projects/{id}/compliance-audits` is optional, and an empty body (what the Run Audit button
sends) resolves frameworks, evidence scope and depth from `effective_compliance_policy`. The
three-step wizard that used to ask them is gone. A *configured* narrative preference downgrades to
deterministic when no AI provider is active — the verdicts are identical either way — while an
explicit `depth: "with_ai_narrative"` still 409s.

**Audit log** (`services/audit_service.py`, `routers/audit_logs.py`): `record()` is the only
writer and rows are immutable, so all read-side shaping happens on the way out.
`classify(action, project_id)` buckets a row as `privilege` (sign-ins, roles, members, API keys,
credentials), `project` (scoped to a project) or `admin` (portal-wide) — privilege wins over the
other two so an access change inside a project isn't buried in scan traffic. It matches the action
*name* rather than reading a stored field, deliberately: a stored category would only classify rows
written after it shipped. `GET /audit-logs` takes `days` (default 1) and `category`, and returns
per-category counts over the whole window next to the page — counts describe the window, never the
filtered slice. There is no pager yet; the page states how many events it dropped rather than
letting a truncated list read as the whole day.

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

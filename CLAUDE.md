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

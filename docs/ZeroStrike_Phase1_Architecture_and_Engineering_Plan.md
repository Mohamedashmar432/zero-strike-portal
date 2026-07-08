# ZeroStrike Portal — Phase 1 Architecture & Engineering Plan (Refined)

## Context

The user has an existing draft (superseded by this doc) describing a SaaS portal (Next.js + FastAPI + MongoDB) that orchestrates scans for an independently-developed Go SAST engine. The draft was directionally correct but written without inspecting the actual scanner code, so its scanner-integration assumptions (CLI flags, upload flow) didn't match reality. This plan verifies those assumptions against the real scanner repo (`zero-strike-code-scanner`, sibling directory), fills in concrete data models/API contracts/folder structure, and locks in a minimalistic, dark, AppSec-tool UI direction.

Key discovery during exploration: **the real Go scanner has zero auth/upload capability today** — it's a purely local CLI (`zerostrike scan <path>` → JSON/SARIF/HTML to stdout/file). Per the user's decision, this plan specs the future upload contract precisely (new flags, HTTP calls, payload shapes) as a hand-off spec for the scanner repo, without touching that repo's code.

User decisions locked in:
1. Scanner-side auth/upload work is spec'd here, built later, in the other repo.
2. Sprints 1–3 (Foundation/Auth, Projects & API Keys, Local Scanner Integration) planned in full depth; Sprints 4–6 (Cloud OAuth, CI/CD templates, Dashboard polish) stay directional.
3. Deployment target: single VM/VPS via Docker Compose, MongoDB Atlas as the only external managed service.
4. UI: dark, terminal-adjacent AppSec aesthetic (Snyk/Wiz/GitHub Advanced Security) — no light mode in Phase 1.

---

## 1. Repo & Folder Structure

**One monorepo, `zero-strike-portal`, with `/frontend` and `/backend`.** The scanner stays a fully separate repo (own release cadence, own versioning, zero code dependency) — bundling it in would violate "keep the scanner independent." Frontend+backend are two halves of one product for a solo/small team, so one repo, one CI pipeline, no cross-repo version pinning for API contract changes.

```
zero-strike-portal/
  frontend/                      # Next.js 15 app
  backend/                       # FastAPI app
  deploy/
    docker-compose.yml
    Caddyfile
    .env.example
    secrets/                     # gitignored, file-based Compose secrets
  docs/
    ZeroStrike_Phase1_Architecture_and_Engineering_Plan.md
  .github/workflows/             # lint+test for frontend and backend
  README.md
```

### `frontend/` (Next.js 15, App Router)

```
frontend/
  app/
    (auth)/layout.tsx, login/page.tsx, register/page.tsx
    (dashboard)/
      layout.tsx                        # sidebar + topbar shell, auth guard
      dashboard/page.tsx
      projects/page.tsx, projects/new/page.tsx
      projects/[projectId]/
        layout.tsx                      # tab shell: Overview/Scans/Reports/Members/API Keys/Settings
        page.tsx                        # Overview
        scans/page.tsx, scans/[scanId]/page.tsx
        reports/page.tsx
        members/page.tsx
        api-keys/page.tsx
        settings/page.tsx
      admin/users/page.tsx, admin/projects/page.tsx, admin/audit-log/page.tsx
      settings/profile/page.tsx
    layout.tsx                          # root layout, theme provider
    globals.css                         # shadcn CSS variables, dark theme tokens
  components/
    ui/                                 # shadcn primitives (generated)
    severity/severity-badge.tsx, severity/scan-status-badge.tsx
    findings/findings-table.tsx, findings/finding-detail-sheet.tsx
    layout/sidebar.tsx, layout/topbar.tsx, layout/project-tabs.tsx
  lib/
    api/client.ts                       # fetch wrapper, auth header, 401->refresh retry
    api/{auth,projects,api-keys,scans,reports}.ts
    validation/{auth,project,api-key}.schema.ts   # zod schemas
    utils.ts
  query/keys.ts, query/use-{auth,projects,scans,api-keys,reports}.ts
  providers/query-provider.tsx, providers/auth-provider.tsx
  tailwind.config.ts, components.json, next.config.js
```

### `backend/` (FastAPI, layered)

```
backend/
  app/
    main.py                    # create_app(), router mounting, CORS, structlog
    core/
      config.py                # pydantic Settings
      security.py              # JWT encode/decode, password hash, api-key hash/gen
      logging.py                # structlog config
      deps.py                  # get_current_user, require_admin, get_project_membership, get_api_key_scope
    db/mongo.py                 # motor client + Beanie init_beanie(document_models=[...])
    models/                     # Beanie Documents: user.py, project.py, project_member.py,
                                 # api_key.py, scan.py, finding.py, report.py, audit_log.py
    schemas/                    # Pydantic DTOs: auth.py, user.py, project.py, api_key.py, scan.py, report.py, common.py
    routers/                    # auth.py, users.py, projects.py, api_keys.py, scans.py, reports.py
    services/                   # auth_service.py, project_service.py, api_key_service.py,
                                 # scan_service.py, report_ingestion_service.py, audit_service.py
    storage/artifact_store.py   # filesystem read/write, swappable interface for future S3 backend
    background/tasks.py         # BackgroundTasks: ingest_report(), prune_refresh_tokens()
  tests/
  Dockerfile
  pyproject.toml
```

---

## 2. MongoDB / Beanie Document Models

**File storage: local Docker named volume, not GridFS/S3.** Scan artifacts are write-once, read-occasionally files — a bind-mounted volume (`artifacts_data:/data/artifacts` in the backend container, paths `/data/artifacts/{project_id}/{scan_id}/report.{json,html}`) needs zero new services, unlike GridFS (adds Mongo document overhead) or object storage (premature — Phase 2 move once multi-replica/off-VM durability matters). Flagged as a scaling risk in §10.

### `users`
```
id, email (unique idx), password_hash (bcrypt), name,
role: "admin"|"user" (idx), is_active=True,
refresh_tokens: [RefreshTokenRecord] (embedded),
created_at, updated_at, last_login_at
```
`RefreshTokenRecord`: `{jti, token_hash, issued_at, expires_at, revoked_at, user_agent, ip}`

### `projects`
```
id, name (idx), description, owner_id (idx), is_archived=False,
scan_count=0 (denormalized), last_scan_at, created_at, updated_at
```

### `project_members`
```
id, project_id (idx), user_id (idx), role: "owner"|"collaborator",
invited_by, invited_at, accepted_at
# compound unique index: (project_id, user_id)
```

### `api_keys`
```
id, project_id (idx), label, prefix (e.g. "zst_live_ab12", shown in UI),
key_hash (sha256 hex, unique idx — O(1) validate lookup),
created_by, created_at, expires_at (idx), revoked_at, last_used_at, last_used_ip
```
Raw token is never stored — returned exactly once at creation.

### `scans` — orchestration/lifecycle only
```
id, project_id (idx), api_key_id, triggered_by: "cli"|"ci"|"cloud"|"manual",
status: "pending"|"running"|"completed"|"failed" (idx),
scanner_version, hostname, git_commit, branch, scan_label,
started_at, completed_at, error_message, created_at, updated_at
# compound index: (project_id, started_at desc)
# index: (status)
```

### `reports` — ingested artifact/summary, separate from `scans` so JSON ingestion failure never corrupts scan lifecycle state
```
id, scan_id (unique idx, 1:1 with scans), project_id (denormalized idx),
scanner_scan_id (Go scanner's own Report.ScanID — see §5 note on two ID spaces),
scanner_version, started_at, duration_ms (converted from Go ns Duration),
root_path, git_commit, branch, hostname,
stats: ScanStatsEmbedded, diagnostics: [DiagnosticEmbedded],
json_path, html_path, json_uploaded_at, html_uploaded_at, generated_at
```
`ScanStatsEmbedded`: `{files_scanned, files_skipped, files_cached, total_findings, suppressed, by_severity, by_language, by_category, by_kind}` — **all optional/default-empty**, confirmed against the real sample `dvpwa_scan.json` which only populates `FilesScanned/FilesSkipped/FilesCached/TotalFindings/BySeverity/ByLanguage/ByCategory`.

### `findings` — one document per `core.Finding`, flattened for cross-scan querying
```
id, scan_id (idx), project_id (denormalized idx, avoids joining through scans),
finding_id (Go Finding.ID), fingerprint (idx — cross-run dedup/trend identity),
rule_id (idx), rule_name, category,
severity: critical|high|medium|low|info (idx), confidence, message,
location: {file, start_line, end_line, start_col, end_col},
language (idx), evidence: [{snippet, start_line, end_line}],
cwe: [], owasp: [], references: [], metadata: {},
kind: sast|secret|sca|config (idx, absent in older reports),
secret, dependency, config (embedded, all optional),
rationale, remediation, taint_context (optional),
created_at (idx desc, == ingestion time)
# compound index: (project_id, severity, created_at desc) — dashboard "critical/high recent"
# compound index: (fingerprint, project_id) — cross-scan dedup/trend
```
**Every field beyond `id`/`message`/`location` is optional** — the real `dvpwa_scan.json` sample (134 findings, older engine build) is missing `Kind/Secret/Dependency/Config/Rationale/Remediation/TaintContext` entirely. Ingestion models must default missing fields to `None`/`[]`, matched by name.

### `audit_logs`
```
id, actor_type: user|api_key|system, actor_user_id,
action (e.g. "login","project.created","apikey.revoked", ...),
target_type, target_id, project_id (idx), metadata: {},
ip_address, user_agent, created_at (idx desc)
# indexes: (project_id, created_at desc), (actor_user_id, created_at desc), (action)
```

---

## 3. Auth Design

**Hand-rolled with `python-jose[cryptography]` + `passlib[bcrypt]`**, not `fastapi-users` — two roles and one scheme don't justify that library's abstraction overhead.

- **Access token**: JWT HS256, `JWT_SECRET` env, 15-min TTL. Claims: `{sub, role, jti, iat, exp, type:"access"}`.
- **Refresh token**: JWT, 30-day TTL, `{sub, jti, exp, type:"refresh"}` — but validity enforced server-side: on `/auth/refresh`, decode, then check `jti` against that user's embedded `refresh_tokens` array (`token_hash` match, not revoked, not expired). **Rotate on every refresh** (issue new pair, mark old `jti` revoked). **Reuse detection**: a refresh call presenting an already-revoked `jti` revokes every token for that user and forces re-login.
- **Role enforcement**: `deps.get_current_user` loads the `User` from the access JWT; `deps.require_admin` gates `role == "admin"` routes. Project-level access goes through `deps.get_project_membership(project_id)` — platform Admins bypass unconditionally, otherwise a `project_members` row is required.
- **API-key auth is a fully separate dependency chain** (`deps.get_api_key_scope`), used only on scanner-facing routes. Token format `zst_live_<32-byte urlsafe random>`; store only `sha256(hex)` + a 12-char `prefix` for UI display, raw token shown once. Validation hashes the bearer token, looks up by `key_hash`, rejects if revoked/expired, else updates `last_used_at/ip` and attaches `project_id` to the request. Because scanner routes depend on `get_api_key_scope` and user routes depend on `get_current_user`, the two credential types are structurally incapable of crossing into each other's routes.

---

## 4. REST API Contract (Sprint 1–3 scope)

All under `/api/v1`. List endpoints return `{items, total, page, page_size}`.

**`/auth`**: `POST /register {email,password,name}` → `201`; `POST /login {email,password}` → `{access_token,refresh_token,token_type,expires_in}`; `POST /refresh {refresh_token}` → rotated pair; `POST /logout {refresh_token}` → `204`; `GET /me` → current user.

**`/users`** (admin except `/me`): `GET /users`, `GET/{id}`, `PATCH/{id}` (role, is_active), `DELETE/{id}`, `PATCH /users/me`.

**`/projects`**: `POST {name,description?}` → `201`; `GET ?page&page_size` (own for User, all for Admin); `GET/{id}`; `PATCH/{id}`; `DELETE/{id}`; `GET/{id}/members`; `POST/{id}/members {email,role}`; `DELETE/{id}/members/{user_id}`.

**`/apikeys`**: `POST /projects/{id}/apikeys {label,expires_at}` → `201 {token,...}` (shown once); `GET /projects/{id}/apikeys` (no raw token); `DELETE /apikeys/{key_id}` → `204`; `GET /apikeys/me` (Bearer `<token>`, scanner preflight) → `{valid,project_id,project_name,expires_at}`.

**`/scans`** — user-facing (JWT): `GET /projects/{id}/scans` (filter by status); `GET /scans/{id}`; `DELETE /scans/{id}`.
Scanner-facing (API-key Bearer): `POST /scans {project_id,scanner_version,hostname?,git_commit?,branch?,scan_label?}` → `201 {scan_id,status:"pending"}`; `PUT /scans/{id}/status {status:"failed",error_message}`; `POST /scans/{id}/upload/json` (raw Report JSON body) → `{status:"completed",findings_ingested}`; `POST /scans/{id}/upload/html` (multipart `file`) → `{html_available:true}`.

**`/reports`**: `GET /scans/{id}/report` → `{scan,stats,findings[...paginated],diagnostics}`; `GET /scans/{id}/report/download?format=json|html`; `GET /projects/{id}/findings` (filter severity/kind/category/fingerprint, paginated); `GET /findings/{id}`.

---

## 5. Scanner Integration Contract (spec only — no code changes to `zero-strike-code-scanner` this session)

Verified directly against `cmd/zerostrike/scan.go`, `internal/report/report.go`, `internal/report/json/json.go`.

**New flags on `zerostrike scan`**: `--server string`, `--token string`, `--project-id string`, `--scan-label string`. Upload mode activates only when server+token+project-id are all set — additive, matches the draft doc's existing example command.

**New subcommand `zerostrike upload`**: `zerostrike upload --report ./report.json [--html ./report.html] --project-id proj_123 --server ... --token ...` — for CI-decoupled scan/upload steps or retry-after-network-failure.

**Two ID spaces — do not conflate**: `Report.ScanID` in the JSON is a client-generated UUID (local cache/grouping identity). The portal's `scan_id` is a server-assigned Mongo ObjectId from `POST /scans`, used in all upload URLs. Store the scanner's ID as `reports.scanner_scan_id` for cross-reference only.

**HTTP calls the scanner makes**:
1. `POST /api/v1/scans` (Bearer token) → `201 {scan_id,status:"pending"}`. A 401 here means invalid/expired/revoked token — scanner must fail fast without running the pipeline.
2. Scanner runs `pipeline.Run` unchanged (no network during scanning).
3. `POST /api/v1/scans/{scan_id}/upload/json` — raw bytes as `jsonreport.New().Render()` would produce. **Constraint** (confirmed via `internal/report/json/json.go` + its tests: `TestJSONReporter_Render_Grouped` proves `GroupBy` set → top-level `Groups` key replaces `Findings`): upload mode must force `GroupBy = GroupByNone` for the uploaded body regardless of any `--group-by` flag, which still applies to the local `--output` file. Otherwise ingestion silently breaks on a shape it doesn't expect.
4. `POST /api/v1/scans/{scan_id}/upload/html` (multipart) — optional; per "JSON = source of truth," only the JSON upload flips `status` to `completed`.
5. Local `--output` writing is unaffected — upload is additive, so a network failure never costs the user their local report.

**Exit codes** (extending, not replacing, today's "1 if findings"): `0` clean; `1` findings exist (unchanged); `2` scan succeeded but upload failed (auth/network/5xx) — lets CI distinguish "found vulnerabilities" from "couldn't report them"; existing non-zero codes for pipeline failure unchanged.

**Portal-side ingestion**: Go JSON is untagged PascalCase (`ScanID`, `RuleID`, `StartLine`...). `backend/app/schemas/report.py` declares fields with exact PascalCase aliases; `report_ingestion_service.py` maps that DTO into snake_case Beanie documents — a direct field-mapped transform, every optional field defaulting to `None`/`[]` so older-build reports (like `dvpwa_scan.json`) ingest cleanly.

---

## 6. Local Scan Sequence Flow (concrete)

1. `POST /api/v1/projects {name}` → `201 {id}`.
2. `POST /api/v1/projects/{id}/apikeys {label,expires_at}` → `201 {token}` (shown once).
3. User downloads CLI binary (static downloads page, outside this API contract).
4. Portal renders copyable command: `zerostrike scan . --project-id {id} --server https://portal... --token {token}`.
5. User runs it.
6–7. Scanner → `POST /api/v1/scans` (Bearer token, body `{project_id,scanner_version,hostname}`) → backend validates token/project/expiry, creates `scans` doc (`pending`) → `201 {scan_id}`.
8. Scanner runs pipeline locally (unchanged).
9. Scanner → `POST /scans/{scan_id}/upload/json` → backend writes `/data/artifacts/{project_id}/{scan_id}/report.json`, runs ingestion (bulk-insert `findings`, create `reports` doc), sets `scans.status="completed"`, updates `projects.scan_count`/`last_scan_at` → `200`. Then → `POST /scans/{scan_id}/upload/html` → writes `report.html`, sets `reports.html_path` → `200`. (Scan is marked complete inside the JSON-upload response — no separate "mark complete" call.)
10. Frontend Scans tab (TanStack Query, refetch-on-focus/poll) sees `completed`; Reports tab's `GET /scans/{id}/report` now returns populated findings.

---

## 7. UI/UX Plan

**Dark-only theme** (shadcn CSS variables in `frontend/app/globals.css`, no light-mode toggle in Phase 1). Base surfaces: background near-black (`slate-950`), card surface `slate-900`, borders `slate-800`, primary text `slate-100`, muted text `slate-400`. Typography: **Inter** for UI chrome, **JetBrains Mono / IBM Plex Mono** for anything code-shaped (snippets, file paths, rule IDs, tokens).

Severity color tokens (`tailwind.config.ts` → `theme.extend.colors.severity`):

| Severity | Color |
|---|---|
| critical | `#ef4444` (red-500) |
| high | `#f97316` (orange-500) |
| medium | `#fbbf24` (amber-400) |
| low | `#0ea5e9` (sky-500) |
| info | `#94a3b8` (slate-400) |

`<SeverityBadge severity="critical">` (built with `class-variance-authority`, a shadcn dependency already) is reused across findings tables, scan cards, dashboard counters. `<ScanStatusBadge status="running">` covers pending/running/completed/failed with its own neutral/blue-pulsing/green/red set. Findings tables are dense (shadcn `Table`, tight rows, monospace file:line/rule-id columns, severity badge leftmost) — matching the Snyk/Wiz/GHAS reference look.

**Routes**: per §1's `frontend/app/` tree — `(auth)` group for login/register; `(dashboard)` group for the authenticated shell (dashboard, projects list/new, `projects/[projectId]` with the six required tabs, `admin/*`, `settings/profile`).

**Data fetching**: TanStack Query only, no Redux/Zustand. One hook module per resource under `query/`, shared key factory in `query/keys.ts`, mutations invalidate relevant list keys on success. Access token lives in memory via `auth-provider.tsx` (never `localStorage`); refresh token is an httpOnly/secure/same-site=lax cookie — viable because Caddy fronts both apps under one apex domain (`/api/*` → backend, `/*` → frontend), making it same-origin. `lib/api/client.ts` injects the access token and transparently retries once through `/auth/refresh` on a 401. React Hook Form + Zod schemas live under `lib/validation/*.schema.ts`, colocated by resource.

---

## 8. Deployment Layout

**Caddy, not nginx**, as reverse proxy — automatic Let's Encrypt HTTPS with a five-line Caddyfile (no separate certbot cron job), and path-based routing (`/api/*` → backend, else → frontend) is all Phase 1 needs. nginx's extra flexibility isn't needed yet and would mean bolting on cert management separately.

```yaml
# deploy/docker-compose.yml — service list
services:
  frontend:   # Next.js standalone build, internal :3000
  backend:    # FastAPI + uvicorn, internal :8000
  caddy:      # :80/:443, Caddyfile handles TLS + routing
volumes:
  artifacts_data:   # mounted at /data/artifacts in backend
```
MongoDB Atlas is external — not a compose service.

**Secrets**: root `.env` (gitignored, `.env.example` committed) via `env_file:` for ordinary config (`MONGODB_URI`, `CORS_ORIGINS`, `ARTIFACT_STORAGE_PATH`, `NEXT_PUBLIC_API_BASE_URL`, `CADDY_DOMAIN/EMAIL`). For `JWT_SECRET` and `MONGODB_URI` specifically, use Compose's file-based `secrets:` block (works without Swarm) pointing at `deploy/secrets/{jwt_secret,mongodb_uri}.txt` (gitignored, `chmod 600`), mounted at `/run/secrets/*` — a lightweight middle ground for a single VM, not Vault/K8s secrets.

---

## 9. Revised Sprint Plan

### Sprint 1 — Foundation (deep)
Repo scaffold (`frontend/`, `backend/`, `deploy/`, CI lint+test). FastAPI skeleton: `core/config.py`, `core/logging.py`, `db/mongo.py` (Beanie init with all 8 Documents registered up front). `users` Document + `auth_service` + `security.py` (JWT encode/decode, bcrypt, refresh rotation/reuse-detection). Routers: register/login/refresh/logout/me. `deps.get_current_user`/`require_admin`. `GET/PATCH /users`, `/users/me`. `audit_logs` Document + `audit_service`, wired into login/logout. Next.js scaffold: shadcn init, dark theme tokens, `(auth)` routes, `auth-provider`/`query-provider`, `lib/api/client.ts` refresh-retry. Docker Compose skeleton, `.env.example`, Atlas connection verified end-to-end.
**Deliverable**: working register/login/refresh/logout, provable Admin-vs-User enforcement, audit log entries for auth events.

### Sprint 2 — Projects & API Keys (deep)
`projects`/`project_members`/`api_keys` Documents. `project_service` CRUD + ownership checks, `deps.get_project_membership`. Routers: full `/projects` CRUD, members invite/list/remove, api-key create/list/revoke, `/apikeys/me`. `api_key_service`: token gen (`zst_live_` + `secrets.token_urlsafe(32)`), sha256 hash, prefix, expiry/revocation. Audit events for project/apikey/member actions. Frontend: Projects list/new/detail shell with six tabs (Members + API Keys functional, others stubs), API-key creation modal with "shown once" UX.
**Deliverable**: full project management + scanner-facing API key issuance/validation, provable via `GET /apikeys/me`.

### Sprint 3 — Local Scanner Integration (deep)
`scans`/`reports`/`findings` Documents, `artifact_store.py`. `scan_service`: `POST /scans` (via `get_api_key_scope`), `PUT /scans/{id}/status`. `report_ingestion_service`: parse aliased PascalCase DTOs, bulk-write findings, write reports doc, flip scan status, update project denorm fields — run via `BackgroundTasks` so the upload call returns fast. Routers: upload/json, upload/html, report get/download, project findings, single finding. Frontend: Scans tab (list, status badges, polling), scan detail with dense findings table, Reports tab (download JSON/HTML).
**External/parallel track**: add `--project-id/--server/--token`/`zerostrike upload` per §5 to `zero-strike-code-scanner` — happens in that repo, is a hard dependency for end-to-end testing. Until it lands, develop/test ingestion against manually-crafted requests using the real `dvpwa_scan.json` sample, and keep a manual "upload report file via UI" fallback even after CLI upload ships.
**Deliverable**: local scanner fully integrated — a real `zerostrike scan` run produces a browsable report in the portal.

### Sprint 4 — Cloud Scanning (directional)
GitHub/Azure DevOps/GitLab OAuth app registration + token exchange. Repo/branch picker UI. Server-side clone-to-temp-dir → invoke Go scanner binary → same upload/ingestion pipeline as Sprint 3 → delete clone. Source never persisted beyond scan lifetime.

### Sprint 5 — CI/CD Integration (directional)
Pipeline snippet generator (GitHub Actions/Azure Pipelines/GitLab CI) reusing the project's API key + scan command. Per-provider docs page; scan history distinguishes `triggered_by:"ci"`.

### Sprint 6 — Dashboard & Polish (directional)
Dashboard widgets via the findings/scans aggregation indexes built in Sprint 3. Search/filtering on findings, Admin audit-log UI, responsive pass, test coverage, docs.

---

## 10. Open Risks / Assumptions

- Local-volume artifact storage doesn't survive beyond a single VM/single backend replica — revisit with S3-compatible storage before scaling horizontally.
- No rate limiting yet on `/auth/login` or scanner-facing endpoints — add a simple per-IP/per-key limiter before public launch.
- Embedded `refresh_tokens` arrays on `users` need pruning (TTL cleanup or max-length cap) or they grow unbounded for long-lived accounts.
- Sprint 3 has a hard external dependency on `zero-strike-code-scanner` shipping the §5 contract — the manual UI-upload fallback exists specifically so the portal isn't blocked end-to-end on that repo's timeline.
- `FastAPI BackgroundTasks` has no retry/dead-letter mechanism — fine at Phase 1 volume, but a crashed ingestion task is currently just lost; revisit if volume grows before Redis/Celery is justified.
- Refresh-token-in-httpOnly-cookie design assumes frontend+backend share an apex domain behind Caddy; separate domains later would need a BFF rework.
- `--group-by` on the scanner changes JSON shape (`Groups` vs `Findings`, confirmed in `internal/report/json/json_test.go`) — the upload path must always force ungrouped output; this must be enforced in the scanner repo's implementation, not just documented here.

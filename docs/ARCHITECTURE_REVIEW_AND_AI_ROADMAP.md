# Architecture review + AI analysis/auto-fix roadmap

Full read-only audit of the backend, frontend, and deploy/CI surface, done ahead of the
next major feature: AI-powered finding analysis and AI auto-fix. Both need to call an
external LLM repeatedly, per-project, on a schedule the user doesn't control (batch
enrichment across many findings, single-shot patch generation) — a different
failure/latency/cost profile than the existing "clone a repo, run a subprocess, save a
report" cloud-scan pipeline. This document is the gap list plus the design that follows
from it, checked in so it's the source of truth for execution rather than a scratch note.

Two decisions shaped this plan:
1. The sibling `zero-strike-cli` repo already has a working, shipped AI-analysis +
   auto-fix implementation (Python, `litellm`-based, multi-provider). The portal
   replicates that design rather than inventing a new one.
2. Scale-out priority right now is fast UX and easy feature expansion, not multi-replica
   infra — foundation fixes below address correctness/extensibility gaps that would hurt
   any growth path; replica/load-balancer work is deferred to a later phase triggered by
   actual load.

Auto-fix's human-review-vs-auto-apply policy is explicitly deferred — the AI Auto-Fix
phase below only builds proposal generation + diff review, matching the CLI's
confidence-gated proposal model and the already-stubbed "Apply Auto-Fix" button. Nothing
auto-commits.

---

## Part 1 — Architecture gaps found (ranked by relevance to this initiative)

### Backend

- **G1 — `motor` is a dead driver.** `backend/pyproject.toml:8-12`: Beanie is pinned
  `<2.1` specifically because `beanie>=2.1` calls a `motor` method that MongoDB's
  now-unmaintained driver (no releases past 3.7.1) never implemented — real Mongo
  connections would crash at startup otherwise. Not urgent to fix today, but don't add
  more motor-specific code, and track a future migration to pymongo's native async driver
  before this becomes a hard blocker.
- **G2 — no retry/backoff anywhere.** `cloud_scan_service.py` gives git-clone and the
  scanner subprocess exactly one attempt each, bounded only by `scan_timeout_seconds`. No
  `tenacity`/`backoff` dependency exists. LLM calls fail transiently far more often than a
  local subprocess — this gap becomes actively harmful for AI features, not just untidy.
- **G3 — job durability is timeout-reap only, not real recovery.**
  `scan_queue_service.py`: one `asyncio.Task` poll loop per process (`main.py:48`), atomic
  `find_one_and_update` claim (`scan_queue_service.py:46-61`, correctly multi-replica-safe),
  but `reap_stuck_scans()` (lines 77-90) just marks anything stuck >45min as terminally
  `failed` — no `retry_count`, no requeue, no dead-letter. Fine for a single bounded SAST
  subprocess; not fine for an LLM call that times out transiently and should just retry.
- **G4 — observability is configured but dead.** `structlog` is a dependency and
  `core/logging.py` sets up JSON/contextvars output, but every real call site
  (`main.py`, `cloud_scan_service.py`, `scan_queue_service.py`, `email_service.py`,
  `auth_service.py`) calls stdlib `logging.getLogger(__name__)` instead — the structlog
  machinery never fires. No request-id propagation, no metrics/tracing (grepped the whole
  repo for sentry/prometheus/opentelemetry — zero hits). `GET /health`
  (`main.py:88-90`) is a static `{"status":"ok"}`, no Mongo/scanner-binary check.
- **G5 — API keys have no scope/kind field.** `core/deps.py:35-39` (`ApiKeyContext`) and
  `models/api_key.py` carry only `project_id`/`key_id` — every key is functionally
  identical. No way to give a future AI-agent principal a distinct, limited identity from
  the scanner CLI's key. Cheap to add a `scope` field now; a schema migration later.
- **G6 — `Report` already has a documented ~10MB ceiling.** `models/report.py:42-43`
  stores `raw_json`/`raw_html` inline. AI enrichment/remediation content (prompts,
  responses, diffs) must get its own collections from day one, not pile onto `Report` or
  `Finding`.
- **G7 — concrete bug: scanner version pin drift.** Three different defaults for the
  same pin: `backend/Dockerfile:10` (`v0.24.0`), `deploy/docker-compose.yml:7`
  (`v0.23.1`), `deploy/.env.example:20` (`v0.23.0`). Collapse to one source of truth.
- **G8 — in-memory rate limiter, documented as not replica-safe** (`core/rate_limit.py`).
  Accepted tradeoff today. New AI endpoints need their own cost-aware limiting regardless
  of replica count — don't build it on this same primitive.
- **G9 — index gaps**: `Project` (`models/project.py`) has no compound
  `(owner_id, is_archived)` index despite that being the standard list-view filter;
  `ApiKey` has no `(project_id, revoked_at)` for "active keys" queries; `AuditLog` has
  only single-field indexes, not compound.

### Frontend

- **G10 — zero test infrastructure.** No vitest/jest/playwright config, no test files, no
  test script in `package.json`.
- **G11 — no diff/code-viewer capability at all.** `components/findings/code-snippet.tsx`
  is a plain HTML table, single-snippet, no highlighting. Nothing to extend for auto-fix's
  diff review — needs one new dependency + component.
- **G12 — no query-key factory.** ~56 `useQuery`/`useMutation` sites across 17 files build
  ad hoc key arrays by hand; already drifting (two files independently construct
  `["projects", projectId, "repos"]`). AI features will add ~10+ more call sites.
- **G13 — 100% client components**, zero RSC data fetching, zero `loading.tsx`/
  `error.tsx`/Suspense anywhere. Directly relevant since fast UX is a stated goal here.
- **G14 — no code-splitting** (zero `next/dynamic` usage) — a diff/editor dependency for
  auto-fix would otherwise bloat the main bundle.
- **G15 — role gating is purely presentational**, ad hoc `user?.role === "admin"` checks
  in nav components, no `middleware.ts`, no reusable guard hook.
- **Not a gap — a head start**: the UI already anticipates this exact feature.
  `scans/[scanId]/page.tsx:49-56` has "Analyze with AI"/"Apply Auto-Fix" buttons wired to
  `notifyComingSoon()`, and `settings/ai-provider/page.tsx` +
  `settings/auto-fix/page.tsx` are already scaffolded empty-states pointing at each other.
  The plan below fills these in rather than inventing new entry points.

### Infra / CI

- **G16 — CI never builds the Docker images that actually ship.** `.github/workflows/ci.yml`
  is lint+test+build only; no `docker build`, no CD/release workflow at all. Deploy is a
  manual `git pull && docker compose up -d --build` on the VM.
- **G17 — no resource limits, 1 backend replica, no load-balancer config** in
  `deploy/docker-compose.yml` — deferred for now, but worth knowing the queue's claim
  logic (G3) is already replica-safe whenever this becomes a priority.
- **G18 — secrets mechanism** (Compose file-secrets, `core/config.py:5` `secrets_dir`)
  extends mechanically to an AI provider key with zero new tooling — this is the
  mechanism the AI Analysis phase uses.

---

## Part 2 — AI feature design (modeled on `zero-strike-cli`)

Reference implementation read in full: `zero-strike-cli/src/analyzers/agent_runner.py`,
`zero-strike-cli/src/agents/security_remediation_agent.py`,
`zero-strike-cli/src/services/scan_service.py`, `src/schemas/remediation.py`,
`src/database/models.py`. `zero-strike-code-scanner` (the Go SAST engine) has no AI
integration — it is not the source for this pattern.

**Provider layer**: adopt `litellm` (same as the CLI) instead of writing a custom
provider interface — one dependency buys every provider the CLI supports, addressed by
model-string prefix:

| provider | default model | notes |
|---|---|---|
| anthropic | `claude-sonnet-4-6` | native |
| openai | `gpt-4o` | native |
| lmstudio | `openai/loaded-model` | local, needs `api_base` |
| kimi (Moonshot) | `openai/moonshot-v1-32k` | openai-compatible |
| nvidia-nim | `nvidia_nim/meta/llama-3.1-70b-instruct` | litellm prefix |
| openrouter | `openrouter/openai/gpt-4o` | litellm prefix |
| custom | user-defined | forced `openai/` prefix |

### A. AI Analysis (enrichment)

Mirrors `SecurityAgentRunner`, extended to two levels (per-finding and whole-report) and
to a verdict/quality-review capability beyond what the CLI does:

- AI only judges/enriches findings a deterministic scan already produced — it never
  invents new findings (carry this constraint into the system prompt verbatim).
- **Per-finding analysis** — `ai_finding_insights`, keyed by `(fingerprint, project_id)`,
  not stored on `Finding` itself, because `report_ingestion_service.ingest()`
  deletes/recreates `Finding` docs every scan; keying by fingerprint lets a stable finding
  across rescans reuse its cached enrichment instead of re-paying for an LLM call every
  time. Fields, beyond the CLI's OWASP/CWE/CVSS/explanation set:
  - `is_false_positive: bool | None`, `false_positive_confidence: float` — the AI's
    verdict on whether the scanner's finding actually holds up, with reasoning
    (`verdict_reasoning: str`).
  - `improved_description: str | None` — an AI-refined explanation of the vulnerability
    and a sharper recommendation than the raw scanner `rationale`/`remediation` text.
  - The raw scanner-produced `Finding.message`/`rationale`/`remediation` are never
    overwritten — AI output is stored and displayed as a clearly separate "AI Analysis"
    layer alongside "Scanner Details," so the original detection stays
    traceable/auditable (this matters for a security tool: nobody should wonder whether a
    finding was quietly rewritten by a model).
- **Report-level analysis** — new collection `ai_scan_insights`, keyed by `scan_id`. This
  is what the page-level "AI Analysis" button (`scans/[scanId]/page.tsx:369-376`, already
  stubbed) triggers: dispatches enrichment for every un-cached finding in the scan, then a
  synthesis step that reduces the stored per-finding insights (counts of likely false
  positives, top themes, prioritized recommendations across the whole scan) into one
  scan-level narrative — one extra summarization call over already-computed data, not a
  second full pass.
- Batch by `rule_id` before calling the LLM (same as the CLI).
- Retry: adopt the CLI's exact policy — 3 retries, exponential backoff from 5s, plus
  static inter-call delays for known rate-limited providers (NVIDIA NIM 1.6s, Kimi 1.1s).
  Implement with `tenacity` — this is G2's concrete fix for the AI path.

### B. AI Auto-Fix (remediation)

Mirrors `SecurityRemediationAgent`:
- Single-shot `litellm.completion(temperature=0, response_format={"type":"json_object"})`
  per finding; same strict JSON contract (`can_fix`, `confidence_score`, `original_code`,
  `patched_code`, `explanation`, `patch_scope`).
- Confidence gate carried over verbatim: only `can_fix=True and confidence_score>=80`
  surfaces as actionable.
- New collection `ai_fix_proposals`, keyed by `finding_id`, status
  `proposed|applied|dismissed`. Produces a reviewable diff only — no PR/commit/auto-apply
  (that policy decision is explicitly deferred).
- Both A and B run as job kinds on the generalized job-queue (Part 1 G3 fix) — no new
  infra, same atomic-claim pattern the codebase already trusts for cloud scans.

### Provider config & secrets

**Revised 2026-07-16**: `AIProviderConfig` is a **global, admin-only singleton** (one document for
the whole portal, mirroring `WorkspaceSettings`'s "at most one document ever exists" pattern) —
**not** per-project as originally scoped below. This was confirmed during Analysis-MVP planning:
the product requirement is "any LLM model, set by the portal admin," and the frontend settings page
was already scaffolded under global Settings (not a per-project tab), so per-project scoping would
have meant moving the UI and adding per-project credential storage nobody asked for. Gate reads/
writes with the existing global `role == "admin"` check (`require_admin`/`<RequireRole
role="admin">`), not project membership.

- `AIProviderConfig` fields: `provider` (`anthropic|openai|lmstudio|kimi|nvidia_nim|openrouter|
  custom`), `model_name`, `api_key_encrypted`, `base_url` (plaintext — not credential material),
  `enabled`, `temperature`, `updated_at`, `updated_by`.
- Encrypt the API key with the existing `oauth_encryption_key` Fernet key already in
  `core/config.py:33-36` — same primitive currently used for OAuth tokens, zero new crypto code.
- Frontend: wire a real form into `settings/ai-provider/page.tsx` (provider dropdown, API key,
  base_url, model, enabled toggle), gated admin-only. `settings/auto-fix/page.tsx` stays a stub —
  out of scope until the AI Auto-Fix phase below.

### Frontend delivery

- One new dependency for diff rendering (e.g. `react-diff-viewer-continued`), lazy-loaded
  via `next/dynamic` — fixes G11 and G14 together.
- Extract the existing conditional `refetchInterval` idiom (already used 3x for scan
  status) into one shared polling hook, reused for AI job status.
- Land the query-key factory (G12) and a `<RequireRole>`/`useCan()` hook (G15) before this
  feature adds its ~10 new query hooks and its own settings-page gating.
- **Loading/result states for AI analysis, both levels** — the current buttons are a bare
  toast; this needs real states built on the existing `DataTableCard`/`Skeleton`/`Alert`
  components (extend the existing loading pattern, don't reinvent it):
  - Per-finding, inside `FindingItem`'s expanded panel (`scans/[scanId]/page.tsx`): idle
    (button) → loading (button shows a spinner + disables, panel area shows a skeleton) →
    result (a verdict badge — "Likely valid" / "Possible false positive" + confidence —
    plus the improved description/recommendation, rendered as a distinct "AI Analysis"
    section next to "Scanner Details", not merged into it).
  - Report-level, at the top of the scan page: a progress affordance while the batch runs
    (e.g. "Analyzing 12/48 findings…" via the shared polling hook) followed by a summary
    card (reusing `StatCard`/`Alert`) showing the scan-level narrative, false-positive
    count, and top recommendations once `ai_scan_insights` is ready.

---

## Part 3 — Phased execution

**Foundation** (independent of AI work, do first):
1. Fix scanner version pin drift (G7).
2. Add `tenacity`; wrap external calls with retry/backoff (G2).
3. Generalize `scan_queue_service.py` into a shared job-queue (job-kind discriminator,
   `retry_count`/`max_attempts`/dead-letter status) so cloud-scans and future AI jobs
   share one durable queue (G3).
4. Swap stdlib `logging.getLogger` → `structlog.get_logger` at existing call sites; add
   request-id middleware; upgrade `/health` to check Mongo + scanner-binary presence (G4).
5. Add a `scope` field to `ApiKey`/`ApiKeyContext`, default `"scanner"` (G5).
6. Create `ai_finding_insights`/`ai_fix_proposals`/`ai_scan_insights` collection
   skeletons now (G6).
7. Frontend: minimal vitest + RTL harness with a handful of smoke tests (G10); query-key
   factory + shared polling hook + `<RequireRole>` hook (G12, G15).
8. CI: add a `docker build` step for both images as a merge gate (G16).

**AI Analysis MVP**: `litellm` dependency, `AIProviderConfig` + encrypted storage + CRUD
endpoints, wire `settings/ai-provider/page.tsx`; per-finding enrichment job writing to
`ai_finding_insights` (verdict + confidence + improved description, alongside
OWASP/CWE/CVSS/explanation); scan-level synthesis job writing to `ai_scan_insights`; real
"Analyze with AI" (per-finding) and page-level "AI Analysis" (whole report) buttons, each
with proper loading/progress states — not the current bare toast.

**AI Auto-Fix**: remediation job writing to `ai_fix_proposals`, diff-viewer
dependency/component, real "Apply Auto-Fix" button (dispatch → poll → render diff for
review only), wire `settings/auto-fix/page.tsx`.

**Scale-out** (deferred until real load demands it): Mongo-backed rate limiter (G8),
Caddy multi-upstream + per-container resource limits (G17), metrics/tracing once
structured logs alone aren't enough, plan the `motor`→pymongo-async migration (G1).

---

## Verification

- Backend: `pytest`, `ruff check app tests`; new tests for job-queue retry/dead-letter
  behavior and enrichment/remediation services (mock `litellm` calls via mongomock-backed
  tests, matching this repo's existing test conventions).
- Frontend: `npm run build`, `npm run lint`, new vitest smoke tests; then manually drive
  the AI Analysis and Auto-Fix flows in the browser against a test provider key to confirm
  the dispatch → poll → render loop end-to-end.
- Confirm the existing cloud-scan pipeline still passes end-to-end after the job-queue is
  generalized — regression risk is concentrated there.

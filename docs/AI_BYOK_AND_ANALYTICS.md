# Project BYOK and AI usage analytics

## The problem

Every LLM call in the portal used to resolve the same global `AIProviderConfig`. One portal admin
owned one key, and every project's AI Analysis, Auto-Fix and Compliance spend landed on that one
bill, with no way to attribute it and no way for a team to bring their own key.

Usage was recorded, but only for successful, token-bearing, project-attributed calls — no feature
label, no latency, and no failure rows. The only read surface was three lifetime numbers on the
project overview. That is not an AI log, and it cannot answer either of the two questions people
actually ask: *where did the money go*, and *why is AI broken for this project*.

## Project BYOK

One workspace switch, `WorkspaceSettings.project_byok_enabled`, admin-only to write
(`PUT /api/v1/ai/settings`) and readable by any signed-in user (a project owner has to know whether
the BYOK card belongs on their settings page). It defaults **off**.

`AIProviderConfig` gained one field, `project_id`:

| `project_id` | Meaning |
|---|---|
| `None` | Portal-wide, admin-managed. Everything that existed before BYOK. Legacy documents have no such field at all, and Mongo's `{project_id: null}` matches them, so no migration was needed. |
| `<id>` | That project's own key. Only ever visible, editable and usable within that project. |

`is_active` is scoped the same way — at most one active config *per scope*, so a project activating
its own provider never disturbs the portal's or another project's.

### Resolution — full isolation

All of it lives in `ai_provider_config_service.resolve_failover_configs(project_id)`; `llm_client`
just calls it.

- **BYOK off** — the portal-wide chain, for every project. Identical to pre-BYOK behaviour.
- **BYOK on** — a project runs *only* on its own configs. It never falls back to the portal key,
  not even when its own provider is returning 429s, because the entire point is that a project's
  spend lands on the project's bill and nowhere else. A project with no key of its own gets
  `LLMNotConfiguredError` with a message naming the page that fixes it. A call with no project
  attribution has no key it is entitled to use, so it gets nothing rather than silently billing
  the portal.

This is a deliberate trade: turning the switch on disables AI for every project that hasn't added a
key yet. The admin UI says so before the toggle is flipped.

### Credentials

No new crypto. Project keys reuse the same Fernet helpers (`app.core.security.encrypt_secret`) and
the same `oauth_encryption_key` as the portal-wide keys, the same omitted-vs-`clear_api_key` update
semantics, and the same `has_api_key: bool` response contract — the raw key and its ciphertext are
never returned in any form.

The load-bearing access check is that **every scoped lookup passes the expected `project_id`**
(`get_config_or_404(config_id, project_id)`). A config id alone is enumerable; without that check a
member of project A could read, re-key, activate or delete project B's credential. `test_project_byok.py`
covers each of those four verbs.

Who can write: project owner or portal admin (`require_owner_or_admin`), matching every other
project mutation. Collaborators can read the list — provider and model, never the key.

## The AI call log

`AIUsageEvent` is now written for **every** LLM call, success or failure. Failures previously
vanished, which is exactly what made a broken project key undiagnosable.

Fields beyond the original tokens/cost: `config_id`, `scope`, `feature`, `status`, `error_type`,
`duration_ms`.

`feature` is stamped by each caller (`analysis`, `scan_synthesis`, `autofix`, `critic`,
`compliance`, `repo_doc`, `fix_chat`) — one literal per call site, and the only reason a
"spend by feature" breakdown can exist at all. `$40 of Anthropic` is a number nobody can act on.

`duration_ms` is wall-clock for the whole attempt including retry backoff — what a user waiting on
an AI job actually experiences.

**Metadata only, deliberately.** Prompts and responses carry customer source code, findings and
secrets; they are never stored. `error_type` is the exception class name, never the raw provider
message, which can echo prompt content back.

### Retention

A fixed 180-day TTL index on `created_at`. The collection is unbounded (one row per call) and prod
runs on an Atlas M0 with a 512MB cap. Lifetime totals survive on `AIProviderConfig` regardless, so
expiry only costs old detail. Not configurable — make it so if someone asks for longer history.

## The dashboard

`ai_analytics_service` reads the log at two scopes, distinguished by exactly one parameter:

- `project_id=<id>` — that project's calls. `GET /projects/{id}/ai-analytics`, `.../ai-events`,
  `require_member`.
- `project_id=None` — portal scope, every project. `GET /admin/ai-analytics`, `.../events`,
  router-level `require_admin` (it spans projects the caller may not belong to).

One `$facet` per request, so a dashboard is a single round trip rather than five: totals, a daily
time series, and breakdowns by feature, by model, and — portal scope only — by project.

Because the response shape is identical at both scopes (`by_project` is simply empty for a project),
**one frontend component renders both**: `components/ai/ai-analytics-dashboard.tsx`, mounted as the
project's *AI Usage* tab and as `/admin/ai-analytics`.

Charting notes: the repo's chart tokens are a neutral lightness ramp, so the dashboard stays in that
system rather than introducing a categorical palette. The breakdown bars are a magnitude comparison
across categories — one measure, so a single mark colour is correct and the axis labels carry
identity. The time series offers a metric toggle (cost / requests / tokens) rather than a second
y-axis: cost and request counts differ by orders of magnitude, and a dual-axis chart would make
their crossings look meaningful when they are an artifact of the two scales. Failure status carries
an icon and the error type, never colour alone. An empty window renders a real empty state and 100%
success — no calls is not "everything failed", and no number is ever fabricated to fill a chart.

## Verification

```
cd backend && ./.venv/Scripts/pytest && ./.venv/Scripts/ruff check app tests
cd frontend && npm run lint && npx vitest run && npm run build
```

Relevant suites: `test_project_byok.py` (switch, CRUD, cross-project isolation),
`test_llm_client_byok.py` (resolution, no-fallback, per-project tool gate, every-call logging),
`test_ai_analytics_api.py` (both scopes, windows, breakdowns, permissions),
`components/ai/ai-analytics-dashboard.test.tsx`.

## Risks

| Risk | Mitigation |
|---|---|
| Turning BYOK on silently breaks AI for keyless projects | Intended isolation; the admin toggle spells out the consequence, and the runtime error names the page that fixes it. |
| A project reads or edits another's credential | Every scoped lookup asserts `config.project_id`; four verbs covered by tests. |
| Usage-event volume on a 512MB Atlas M0 | 180-day TTL index; lifetime totals live on `AIProviderConfig`. |
| Cost figures are estimates | They come from litellm's price table and fall back to `0.0` when it can't price a model. Labelled "Estimated from provider pricing" in the UI — not billing-grade. |
| One shared Fernet key for all secret types | Pre-existing (`oauth_encryption_key`, committed dev default, no rotation path). BYOK widens the blast radius; key rotation is still unaddressed. |

# Config Surface Wiring

Branch: `feature/config-surface-wiring`

Closing the gap between config screens that exist and config that is actually persisted,
resolved, and enforced — and making it obvious which settings are portal-admin-only and
which a project owner may override.

## 1. What the audit got right, and what it got wrong

The gap list in `config-gaps.md` is broadly correct. Four items need correcting before
planning against it, because acting on them as written would make the product worse.

**Corrected: (C) Notifications is not "a UI shell".** There is no notification backend at
all — no model, no service, no event emission, no delivery. `email_service.py` is SMTP for
password reset only, and `smtp_host` defaults to empty in every environment. Searching the
backend for `webhook|notification` returns exactly one hit, and it is a word inside the
compliance catalog. This is a build, not a wiring job.

**Corrected: (H) Scan-scoped quota is a decision, not a limitation.** `auto_fix_quota.py`
documents why: a scan is one repo at one commit, so an allowance there is bounded and
refills on the next scan, whereas a project-lifetime cap goes permanently flat and blocks
the repo that is being actively remediated. Project/monthly budget ceilings are a different
feature (spend governance) with their own design. Not folded into this branch.

**Corrected: (I) The static compliance catalog is a safety property.** `SUPPORTED_FRAMEWORK_KEYS`
exists so a framework whose evidence mapping nobody reviewed control-by-control cannot be
run, and a test asserts the current set. Making controls admin-editable removes exactly that
guarantee — an admin would be able to author a mapping that produces a pass verdict off
evidence that does not support it. Recommendation: do not do this. If framework coverage
needs to grow, it grows through reviewed catalog entries.

**Corrected: (E) AI provider precedence is already correct.** `resolve_failover_configs()`
is the single decision point and BYOK isolation is enforced there. The gap is purely that
the UI never tells an admin which config a given project is actually using. That is a
display fix, not a resolution fix.

Also out of scope because they are not config surfaces: `project-attack-sim-tab.tsx`
(unimplemented feature) and `ai_scan_insight.py` (unwritten collection).

## 2. Verified state today

| Surface | Backend | Persisted | Enforced |
|---|---|---|---|
| `/settings/general` | none | no | no — placeholder page |
| `/settings/notifications` | none | no | no — placeholder page |
| Project → Compliance config tab | none | no | no — save button toasts "not stored yet" |
| `/settings/report-templates` | `report_template_service` | yes | yes (project override exists) |
| `/settings/ai-provider` | `ai_provider_config_service` | yes | yes (BYOK precedence enforced) |
| `/settings/auto-fix` | `remediation_settings_service` | yes | yes — but workspace-wide only, no project override |
| `/settings/integrations` | `repo_credential_service` | yes | yes |
| `/settings/data`, scanner status, audit logs, AI analytics | various | n/a | observability, not config |

Scanner flags `--enable-secrets --enable-sca --enable-framework-checks` are hardcoded at
`backend/app/services/cloud_scan_service.py:189` — which is exactly what the General page
claims to configure ("workspace-wide scan defaults").

## 3. Roles

Two independent role axes already exist; no new roles are introduced.

- **Portal admin** — `User.role == "admin"`, enforced by `require_admin`.
- **Project owner** ("project admin") — `ProjectMember.role == "owner"`, enforced by
  `project_service.require_member` plus a role check. `project-settings-tab.tsx` already
  treats `owner` and `admin` as equivalent for project management.

Rule applied throughout: **a project owner may tighten a policy, never loosen one, and never
authorize spend.** Confidence thresholds may be raised but not lowered below the workspace
floor; quota grants stay portal-admin-only.

## 4. Design

No new policy-document abstraction. The codebase already has a working pattern for exactly
this — `WorkspaceSettings` singleton + a nullable field on `Project` where `None` means
inherit, resolved by one helper (`report_template_service.get_effective_template`). Every
policy below follows it.

One new service, `workspace_settings_service.py`, becomes the single owner of the singleton
(`get_workspace_settings` moves out of `report_template_service`, `byok_enabled` keeps
delegating) and holds one `effective_*` resolver per policy area. This replaces scattered
access to the singleton rather than adding a layer on top of it.

## 5. Phases

### Phase 1 — General settings becomes the workspace-default surface (portal admin)

Add to `WorkspaceSettings`, add nullable mirrors to `Project`:

- `scan_enable_secrets`, `scan_enable_sca`, `scan_enable_framework_checks` (default `True`
  — matches today's hardcoded flags exactly, so nothing changes until someone edits it).
  Threaded into `cloud_scan_service` where the argv is built.
- `default_compliance_frameworks: list[str]` — what an audit assesses.

The page also carries the **settings scope map** (gap J): a static table naming, for every
setting in the product, whether it is workspace-only, project-overridable, or inherited, and
where it lives. Cross-links to the pages that already own those controls — the report
template and BYOK toggle are *not* duplicated here.

### Phase 2 — Compliance policy persisted (portal-admin default, project-owner override)

Fields on both `WorkspaceSettings` and `Project` (nullable = inherit):

- `compliance_frameworks` — which supported frameworks this project targets.
- `compliance_audit_scope: "latest" | "history"` (default `"latest"`) — which findings count
  as evidence.
- `compliance_auto_audit_on_scan: bool` (default `False`) — on scan completion, enqueue a
  **deterministic-depth** audit. Deterministic only, so enabling it can never produce
  surprise LLM spend.
- `compliance_evidence_retention_days: int | None` — reaped by the existing
  `compliance_queue_service.poll_loop`, no new scheduler.

New endpoints: `GET/PUT /projects/{id}/compliance-settings` (member read, owner write) and
the workspace equivalent under the General surface.

Rewrite `project-compliance-config-tab.tsx` against those. The "Auto-Generate Remediation
Drafts" switch is **deleted, not persisted** — there is no code path behind it, and a
persisted toggle that does nothing is worse than an absent one.

### Phase 3 — Notifications: in-app centre + email (per user)

Delivery is **in-app and email**; outbound webhooks are not built. Notification preference is
per *user*, which is what `/settings/notifications` already claims ("Choose when the portal
notifies you"), with recipients resolved from project membership and portal role.

- `models/notification.py` — one document per (user, event). `user_id`, `event`, `title`,
  `body`, `project_id`, `link`, `severity`, `read_at`, `created_at`. TTL index expires them
  at 90 days, same treatment as `AIUsageEvent`, so the collection cannot grow unbounded.
- `User.notify_in_app: list[str]` and `User.notify_email: list[str]` — event keys the user
  wants each way. Two plain lists rather than a nested prefs object: the UI is a grid of
  checkboxes and that is exactly the shape it needs.
- `services/notification_service.py` — `notify(event, *, project_id, title, body, link)`.
  Resolves recipients (project members for project events; portal admins for admin events),
  filters by each recipient's prefs, bulk-inserts the in-app rows, and sends email via the
  existing `email_service` in a worker thread. Failures are logged, never raised — a missed
  alert must not fail the scan or fix that triggered it.
- Emission points are where `audit_service.record` is already called, so no new plumbing:
  scan completed / failed, compliance audit completed with failing controls, auto-fix
  proposal created, auto-fix apply failed, quota request raised (admins), quota exhausted,
  scanner unhealthy (admins).
- `GET /notifications`, `POST /notifications/read` (mark one or all). The sidebar bell —
  which today renders a **hardcoded unread dot and toasts "No new notifications"** — becomes
  a real popover driven by that endpoint, unread count polled by TanStack Query.

**Email caveat:** `settings.smtp_host` is empty in every environment today, and
`email_service.send_email` logs a warning and returns when it is. Email delivery is therefore
built and wired but inert until an SMTP host is configured; the notifications page says so
rather than implying mail is going out.

### Phase 4 — Auto-fix policy precedence

- Project-overridable (owner): `enabled` (may disable, not enable past a workspace disable),
  `confidence_threshold` (may only be raised above the workspace floor).
- Portal-admin-only: `auto_fix_findings_per_scan`, `max_findings_per_job`,
  `blocking_severities`, all quota grants.
- `remediation_critic_enabled` and `remediation_critic_skip_dependency_bumps` are shown
  read-only with their env-resolved values, so the skipped/unavailable states the fix-stage
  panel renders are explainable without reading `.env`.

### Phase 5 — Precedence visibility

Every project-level config control renders its resolved source: *"Inherited from workspace
(SOC 2, ISO 27001)"* vs *"Overridden for this project"*, with a link to the workspace
setting. Applied to AI provider, report template, compliance policy, auto-fix policy. Pure
frontend on top of the resolvers from Phases 1–4.

## 6. Not doing

| Item | Why |
|---|---|
| Admin-editable compliance control packs (I) | Removes the reviewed-mapping guarantee that `SUPPORTED_FRAMEWORK_KEYS` exists to provide. |
| Project / workspace / monthly quota budgets (H) | Scan scoping is a documented decision; spend governance is a separate feature. |
| Outbound webhooks (Slack / Teams) | Not asked for. In-app + email is the chosen delivery; a webhook can be added later behind the same `notify()` call. |
| Cron-scheduled audits | No scheduler in the stack. Scan-triggered auto-audit covers the actual need. |
| Attack sim, `ai_scan_insight` | Unimplemented features, not config gaps. |

## 7. What landed

All five phases are implemented on this branch.

**New backend files**
- `app/models/workspace_settings.py` (extended), `app/models/notification.py`
- `app/core/notification_events.py` — the event catalog; `notify()` refuses a key that is not in it
- `app/services/workspace_settings_service.py` — singleton owner + every `effective_*` resolver
- `app/services/notification_service.py`
- `app/routers/workspace_settings.py` (`/workspace-settings`, `/projects/{id}/policy`),
  `app/routers/notifications.py`
- `app/schemas/workspace_settings.py`, `app/schemas/notification.py`

**Modified**
- `Project` gains eight nullable override fields; `User` gains `notify_in_app` / `notify_email`
- `cloud_scan_service` builds the scanner argv from resolved policy instead of hardcoded flags
- `report_ingestion_service.ingest` triggers the auto-audit and the completion notification
- `compliance_queue_service` gains `enqueue_auto_audit` and `reap_expired_audits`
- `report_template_service` is now a thin view over `workspace_settings_service`
- `ai_remediation.py` gates on project-effective policy, not the raw workspace singleton

**New frontend files**
- `lib/api/workspace-settings.ts`, `lib/api/notifications.ts`
- `components/layout/notification-bell.tsx`, `components/projects/project-policy-card.tsx`

**Rewritten frontend**
- `settings/general/page.tsx` — was a "Coming soon" empty state; now workspace scan +
  compliance defaults plus the settings scope map
- `settings/notifications/page.tsx` — was a "Coming soon" empty state; now a real per-user
  event × channel preference grid
- `components/projects/project-compliance-config-tab.tsx` — the "Not stored yet" switches now
  persist; the "Auto-Generate Remediation Drafts" switch was deleted rather than persisted,
  because no code path stands behind it
- `components/layout/sidebar.tsx` — the bell rendered an unconditional unread dot and toasted
  "No new notifications"; it is now the real inbox

**Four bugs found while wiring, fixed here**
1. `Project.get()` raises a `ValidationError` on a non-ObjectId id rather than returning
   `None`. A scan whose `project_id` was stale would have failed outright once policy
   resolution was added to the scan path. `workspace_settings_service.load_project` is the
   safe accessor every caller now uses.
2. `structlog` reserves the `event` kwarg for the log message. `logger.exception(...,
   event=event_key)` raised `TypeError` inside the very handler whose job was to swallow
   errors — so a notification failure would have propagated into the scan that triggered it.
3. Reusing a FastAPI route handler by calling it directly passes the `Query(...)` marker
   object as the parameter value, not its default. `POST /notifications/read` blew up with
   `bad operand type for abs(): 'Query'`. Both handler pairs now share a plain helper.
4. Every notification deep link was written against routes that do not exist. There is no
   top-level `/scans/{id}` or `?tab=` route in this app — scans, auto-fix and compliance are
   all project-scoped (`/projects/{id}/scans/{scanId}`,
   `/projects/{id}/auto-fix/{scanId}`, `/projects/{id}/compliance/{auditId}`). Caught by
   listing the App Router tree rather than by a test, since a dead `href` fails silently.

## 8. Browser QA

Driven against a real MongoDB and a real Chrome (chrome-devtools MCP), signed in through the
actual login form as a portal admin, a project owner, a collaborator and a non-member.

Verified working: workspace defaults save and survive reload; project overrides show
*Inherited* vs *Overridden here* and flip correctly; the tighten-only rule holds through the
UI (threshold set to 10 against a workspace floor of 80 stores 10 but resolves to 80); the
compliance config tab persists with no "Not stored yet" left anywhere; the notification bell
lists real events and mark-all-read clears the badge; preference changes persist; a
collaborator gets a read-only tab with the save button gone and every control disabled; a
non-member is refused. Zero console errors, every API call 200.

**Two bugs the browser found that the test suite had not:**

1. **Non-admins were handed default subscriptions to admin-only events.** Delivery was always
   gated correctly, but `/notifications/preferences` returned the whole catalog, so the UI grid
   and the payload it saved back disagreed — a non-admin pressing Save persisted subscriptions
   to events they can never receive. Fixed by scoping the endpoint to
   `notification_events.visible_events(is_admin=...)`, which makes the event list and both
   channel lists consistent by construction. The frontend's own admin filter became redundant
   and was deleted. Two tests added.

2. **Every notification rendered ~5 hours old.** Motor returns naive datetimes, so the JSON
   carried no offset and the browser's `new Date(...)` read it as local time — wrong by exactly
   the viewer's UTC offset. The codebase already has `core.timeutils.as_utc` for precisely this,
   and its docstring describes this bug; the notifications router simply never called it. Fixed
   there, with a regression test asserting the serialized string carries an offset, plus a
   defensive fallback in `relativeTime()`.

**Pre-existing, NOT fixed here — flagged for a decision.** The same naive-timestamp bug affects
five endpoints this branch does not touch: `/audit-logs`, `/projects` (list and detail),
`/dashboard/stats`, and `/projects/{id}/members`. Every date those render is off by the viewer's
UTC offset — visible in the admin audit log, which showed 6:17 AM for an action taken at 11:47
local. `as_utc` already exists and the fix is mechanical, but it belongs in its own change
rather than being folded silently into a config-wiring branch.

## 9. Tests

Per phase, the smallest check that fails if the logic breaks:

- Resolution precedence: project override wins, `None` inherits, project cannot lower a
  workspace floor.
- Scan flags: a workspace toggle actually changes the scanner argv.
- Auto-audit: a completed scan with the flag on enqueues exactly one deterministic audit;
  with it off, none.
- Notifications: an event delivers only to users who opted into it; an admin-only event never
  reaches a non-admin; a delivery failure does not raise into the caller.
- Role enforcement: a collaborator cannot write project policy; a project owner cannot write
  workspace policy or grant quota.

Delivered as `backend/tests/test_workspace_policy.py` (12), `test_notifications.py` (10) and
`test_scan_policy_wiring.py` (9) — 31 new tests, all passing alongside the existing suite.


## 7. Follow-up — the audit wizard's questions moved into config

`POST /projects/{id}/compliance-audits` originally required `frameworks`, `scope` and
`depth`, and a three-step wizard at `/projects/{id}/compliance/new` asked for all three on
every run. Those are configuration, not per-run decisions: the same team answered the same
way every time, and the wizard stood between them and the one thing they wanted.

Every field on the request is now optional, and an empty body resolves the run from
`workspace_settings_service.effective_compliance_policy`:

| Was asked at run time | Now configured at |
| --- | --- |
| Frameworks | Project → Compliance Config (workspace default in Settings → General) |
| Evidence scope | Project → Compliance Config (`compliance_audit_scope`) |
| AI explanations | Settings → General only (`compliance_audit_ai_narrative`) |
| Repository subset | Not configurable — an audit covers every repository in the project |

Two rules hold here:

- **AI narrative has no project twin.** It authorises LLM spend, so it stays admin-owned
  under `require_admin`, same rule as the auto-fix allowance.
- **A configured narrative preference downgrades; an explicit one refuses.** If the workspace
  asked for narrative but no AI provider is active, the audit runs deterministically and the
  response says so — the verdicts are identical either way, so refusing would be theatre. A
  caller that explicitly sends `depth: "with_ai_narrative"` still gets a 409, because it
  asked for something that cannot be produced.

The wizard route and its `wizardStep` helper are deleted. `Run Audit` on the Compliance
Audits tab posts `{}`, states what the configured run will assess before the click, and
becomes "Audit running…" while one is in flight (the backend returns the active audit rather
than queueing a second).

## 8. Follow-up — the audit log read surface

The admin audit log recorded 60-odd action types but rendered raw ObjectIds for the actor,
no project, no categorisation, and the whole table unfiltered. Three changes, all on the read
side — nothing about how rows are written changed, since audit rows are immutable:

- `audit_service.classify(action, project_id)` buckets a row as `privilege` (sign-ins, roles,
  members, API keys, credentials), `project` (anything scoped to a project) or `admin`
  (portal-wide). Privilege wins over the other two, so an access change inside a project does
  not get buried in scan traffic. Derived from the action name rather than stored as a field,
  so the rows already written classify too.
- `GET /audit-logs` takes `days` (default **1**) and `category`, and returns per-category
  counts over the whole window alongside the page. Counts describe the window, not the
  filtered slice, so the Overview panel does not change when a filter chip is clicked.
- Actor ids resolve to emails and project ids to project names, two extra queries per page.

Pagination is deliberately not built yet: the window *is* the unit, and the page says how
many events it dropped when a window overflows the page size rather than letting a truncated
list read as the whole day.

# Project Insights, merged Operations page, and the cloud-scan quota

Planned 2026-10-28. Three changes that ship together because they share data: an admin page that
answers "what is every project doing and what is failing", the Scanner Status page folded into
Operations, and a per-project monthly limit on cloud scans.

## 1. Cloud-scan quota (per project, monthly, admin-set)

**Rule.** Every project may start `limit` cloud scans per calendar month (UTC). `limit` is
`Project.cloud_scan_monthly_limit` when set, else `settings.cloud_scan_monthly_limit_default`
(30, env `CLOUD_SCAN_MONTHLY_LIMIT_DEFAULT`). CI/CD scans are never limited — they run on the
customer's own runners and cost the portal nothing but ingest.

**What counts.** A cloud `Scan` with `created_at >= start of current UTC month` and
`quota_exempt != True`. `Scan.quota_exempt: bool = False` is set to `True` only for failures the
portal caused, never the customer:
- the scanner binary is missing/unavailable (`cloud_scan_service` fails the scan before cloning);
- the reaper reclaims a crashed/stuck scan (`scan_queue_service.reap_stuck_scans`).

A clone failure (bad token, repo gone), a scanner exit with an error on the customer's code, or a
completed scan all count. Repo Sync's "already up to date" short circuit creates no scan, so it is
free.

**Enforcement.** One choke point: `scan_service.enqueue_repo_scan` — both the manual
create-scan route and Repo Sync go through it. Before inserting, count; if `used >= limit` raise
`HTTPException(409, "Cloud scan limit reached: {used}/{limit} this month. Ask a portal admin to
raise this project's limit.")`. Any background caller of `sync_repo`/`enqueue_repo_scan` (scheduled
or webhook sync, if one exists) must catch that and log/skip rather than crash its loop.
`ponytail:` count-then-insert can overshoot by one under two simultaneous clicks; an atomic
monthly counter is the upgrade if that ever matters.

**Service.** `services/cloud_scan_quota_service.py`:
- `month_start(now) -> datetime`
- `effective_limit(project) -> int`
- `async usage(project) -> CloudScanQuota` (`used`, `limit`, `remaining`, `period_start`, `resets_at`)
- `async ensure_available(project) -> None` (raises the 409)

**API.**
- Project detail/list responses gain `cloud_scan_quota: {used, limit, remaining, period_start,
  resets_at, is_default}` (detail is required; list may reuse it if cheap — one grouped count, not
  N queries).
- `PUT /api/v1/admin/projects/{project_id}/cloud-scan-limit` (`require_admin`), body
  `{"monthly_limit": int | null}` — `null` resets to the default; `0..10000` allowed (0 = cloud
  scanning paused). Audited (`"Cloud Scan Limit Changed"`, metadata old/new), and classified as
  `admin` in `audit_service.classify`.

**UI — project header (the red box in the screenshot).** A compact right-aligned pill on the
project header row, same height as the role/risk badges, mono uppercase:
`CLOUD SCANS  12 / 30` with a thin progress bar underneath and a `title`/tooltip
"Resets Nov 1 (UTC)". Colour: muted under 80%, amber 80–99%, red at 100%. At 100% the scans tab's
"New scan" button is disabled with the same message as the 409, and Repo Sync's button too. Portal
admins additionally see a small pencil that opens an inline number input to change the limit
(plus "Reset to default").

## 2. Project Insights (admin page `/admin/project-insights`)

Nav label "Project Insights", in the ADMINISTRATION group right after Users. Laid out like the
admin Dashboard: `PageHeader`, a `MetricStrip`, then `DataTableCard`s — same components, no new
chart library.

**Date filter.** Presets 24h / 7d / 30d (default) / 90d plus a custom From/To using native
`<input type="date">`, sent as `since`/`until` ISO timestamps (admin's local midnights, like the
audit log). Server caps the range at 366 days.

**`GET /api/v1/admin/project-insights?since&until`** (`require_admin`) →
```
{
  "since", "until",
  "totals": {
    "projects": int,             # all non-archived projects (onboarded)
    "projects_created": int,     # created inside the window
    "repos": int,                # ProjectRepo docs configured
    "cloud":  {"total","completed","failed","active"},   # active = queued+running
    "cicd":   {"total","completed","failed","active"}    # active = pending+running
  },
  "projects": [ {
    "project_id", "name", "is_archived", "created_at", "repos": int,
    "cloud": {"total","completed","failed","active"},
    "cicd":  {"total","completed","failed","active"},
    "last_scan_at", "last_error": {"scan_id","scan_type","message","at"} | null,
    "cloud_scan_quota": {...as above...}
  } ]
}
```
Window counts filter on `Scan.created_at`. Use one `$group` aggregation on the raw collection
(`get_pymongo_collection().aggregate`, as `dashboard_service._severity_groups` explains) keyed by
`project_id, scan_type, status` — not a query per project.

**`GET /api/v1/admin/project-insights/requests?since&until&project_id&scan_type&status&limit&offset`**
(`require_admin`, `limit` ≤ 200) — every scan request in the window, newest first:
`{ total, items: [{scan_id, project_id, project_name, scan_type, triggered_by, status, stage,
repo_url, branch, scan_label, ci_provider, ci_build_url, error_message, created_at, started_at,
completed_at, quota_exempt}] }`. Explicit projection — never read `repo_token`. `repo_url` passes
through the existing URL credential scrubber if one exists (grep `redact`/`scrub`), since a pasted
URL can carry a token.

**Page sections.**
1. Metric strip: Projects onboarded (+N new), Repos configured, Cloud scans (completed · failed),
   Pipeline runs (completed · failed), Failure rate.
2. "Projects" table: name (link to project), repos, cloud scans `done/failed`, pipeline runs
   `done/failed`, quota `12/30` (admin pencil edits it inline via the PUT above), last error
   (truncated, tooltip full), last scan. Sortable by failures.
3. "Requests & errors" table: every request from the second endpoint, filter chips
   All / Failed only, scan type cloud|cicd, project select; error message shown in full in a
   row expander. Paged with the existing Previous/Next pattern. Links: View → scan page,
   CI build URL → external.

Deleted projects: render the name as plain text (no link) — a link to a deleted project 404s.

## 3. Merge Scanner Status into Operations

Scanner Status and Operations both show the cloud-scan queue and recent failures. Keep the
Operations page as the one surface and move over only what Scanner Status has that Operations
does not: **scan engine availability**, **published binaries checklist**, and **clone workspace
disk**. Drop Scanner Status's duplicate queue and failures blocks.
- Frontend: Operations page renders a "Scanner" section (those three blocks) by also calling the
  existing `GET /admin/scanner-status`. Both backend endpoints stay — the admin MCP tools
  (`get_scanner_status`, `get_operations_overview`) use them.
- `/admin/scanner-status` becomes a redirect to `/admin/operations#scanner`; remove its nav link;
  update any in-app links/guide text that point at it.

## Tests (backend, mongomock)
- quota: 30 cloud scans this month → 31st is 409; last month's scans don't count; CI/CD scans
  don't count; a `quota_exempt` scan doesn't count; project override raises/lowers the limit;
  `null` resets to default; non-admin PUT is 403.
- insights: totals/per-project counts respect the window; requests endpoint filters and never
  returns `repo_token`; non-admin is 403.
- reaper / scanner-missing paths set `quota_exempt`.

---

# Part 2 — Control Panel, user activity, Teams digest (planned 2026-10-28, not started)

Status: **plan only — build starts when the user says "go".**

## 4. Rename to Control Panel, with sub-sections

`/admin/project-insights` becomes **Control Panel** (`/admin/control-panel`, old route redirects).
One page, tabs as sub-sections, each tab kept in the URL (`?tab=`) so it can be linked:

| Tab | Contents |
|---|---|
| Overview | People row + Projects row of the metric strip (below), date filter shared by every tab |
| Projects | Today's Project Insights table, plus "created in window" badge; row click → Project activity |
| Project activity | One project: timeline of what happened (scans, members, settings, fixes, audits — from the audit log), its active users, its requests & errors |
| Requests & errors | Today's table, unchanged |
| Teams digest | Digest configuration (section 6) |

## 5. User activity — first-party, no third-party script

**Gap today.** `User.created_at` gives registrations, but successful sign-ins are not audited and
`last_login_at` only moves on a password login — a user on a refresh-token session for a week never
"logs in". So "active today" cannot be computed from what is stored now.

**Change.** One small collection, `user_activity_days`: `{user_id, day: "YYYY-MM-DD" (UTC),
project_ids: [..], first_seen_at, last_seen_at}`, unique on `(user_id, day)`, TTL 400 days.
- Written from `deps.get_current_user` (any authenticated request → user active that day) and from
  `project_service.require_member` when the role comes from membership (→ `$addToSet` that project).
  Portal admins viewing a project they are not a member of are not counted as that project's users.
- Throttled in-process: a `(user, day, project)` seen-set means at most one upsert per key per
  replica per day, so this never adds a write per request. Write failures are logged, never raised.
- `User.last_seen_at` is set by the same upsert path.

**Metrics** (all respect the date filter):
- Registered: total users; new registrations in window (today when the filter is 24h).
- Active: distinct users with an activity day in window; DAU for today; never-signed-in users.
- Pending approval / disabled counts (existing fields).
- Per project: active users in window, members total.
- "Sign-ins" are not counted separately — activity days are the honest measure; adding a
  `User Logged In` audit row is a one-liner if a sign-in count is ever wanted.

## 6. Teams digest (scheduled webhook)

**Where it goes.** The existing encrypted workspace webhook (`WorkspaceSettings.alert_webhook_enc`)
by default, or an optional separate digest webhook, so routine digests don't drown the alert channel.

**Admin config** (`WorkspaceSettings.digest_*`, `require_admin`, audited): enabled; frequency
daily/weekly; send time (UTC hour) and weekday; project selection = *all* or a chosen list; which
blocks to include. A **Send test now** button posts immediately.

**Card** (Adaptive Card 1.5 `Table`, which Teams renders as real rows/columns; `alert_service.post_webhook`
already wraps cards):

| Project | Pipeline runs | Pipeline failed | Cloud scans | Cloud failed | Critical | High | Quota |
|---|---|---|---|---|---|---|---|

followed by a totals row, then a **Scanner health** fact set:
- Engine available on the server; scanner version baked into the backend; latest published binary
  version; **CI runners on an older scanner version** (from `Scan.scanner_version` on recent cicd scans).
- Rule pack version in force + rule count (SAST rules are the scanner's own, versioned via the Scan
  Engine page).
- **Dependency vulnerability data: live from OSV.dev at scan time** (`api.osv.dev`, which aggregates
  GitHub Advisories, NVD-linked CVEs and ecosystem feeds). There is no local CVE database to be
  "loaded" or "patched", so the card never claims a feed date. It reports instead: OSV reachable
  from the server (a cheap probe at send time) and **new CVE/GHSA ids first seen in the selected
  projects during the period** (from findings' advisory ids), with the top few listed.
- Failures needing attention: cloud scans failed, stuck/reaped scans, projects at ≥80% quota.

Critical/High are **current exposure** (latest completed scan per repo, `project_stats_service`),
not a sum over every scan in the period — the same rule the dashboard uses.

**Scheduler.** A lifespan task wakes each minute; when a digest is due it claims the slot with an
atomic `find_one_and_update` on `digest_last_sent_for` (period key), so a restart or a second
replica can never double-send. Every send writes an audit row and is visible in the tab with its
result (sent / webhook error). Webhook URL is vetted with the existing `vet_webhook_url` (SSRF).

### 6a. The digest is several cards, not one (2026-10-30)

**Why.** One card for a 24-project portal was ~40 KB. Teams refuses a message over ~28 KB, and a Power
Automate Workflows webhook answers the portal's POST with 202 *before* it tries to post, so the portal
logged "Digest Sent, 0 errors" while the flow failed with `RequestEntityTooLarge` and nothing appeared.
The portal cannot see that failure, so the only fix is to never send a card near the limit.

**Cards, in order**, each "n/N" in its header so a reader can tell if Workflows reordered them:

1. **Scanner health** (green "Scanner ready, CVE feed live", red "Scanner NOT ready"): scan engine,
   backend scanner version, latest published binary, CI runners on an older scanner, rule pack; then
   **CVE data (OSV.dev)**: the two endpoints the scanner itself calls at scan time (`querybatch` and
   `vulns/{id}`, see the scanner's `internal/scanner/sca/osv.go`) probed from the server with their
   round-trip in ms, when they were checked, and the last dependency scan seen (newest `kind=sca`
   finding); then **new advisories** first reported in the period (id, worst severity, how many projects),
   top 8. There is still no local CVE database to "load": the status is the live feed's reachability plus
   what was first seen. The card never claims a feed date or "CVEs published today" (OSV offers no such
   query); it says "first reported by a project since <period start>".
2. **Project status**, `_ROWS_PER_CARD` (10) per card, worst exposure first, at most `_MAX_PROJECT_CARDS`
   (6, so 60 projects); each ~16 KB.
3. **Summary**: titled with the date ("Security digest, Fri 30 Oct 2026"), "Updated HH:MM UTC" and the
   period, the KPI row (totals always cover every project), a Scanner/OSV fact set, anything left off the
   project cards, and the needs-attention list (failures, scanner or CVE feed not ready, quota >= 80%,
   stale projects). It carries the Open Control Panel button.

**Sending.** `_post_cards` posts a channel's cards sequentially with `_CARD_GAP_SECONDS` (2 s) between
them and stops at the first failure, reporting "card i of N: <error>" (a digest missing its middle is worse
than one that says where it stopped). Channels run in parallel. `DigestSendResponse.cards` is N.
`_MAX_CARD_BYTES` (20 KB) is the budget a test holds every card to (Workflows re-wraps the card in an
escaped message, ~17% larger).

## 7. Microsoft Clarity — dropped (2026-10-28, user decision); recommendation kept for the record

Clarity records sessions and heatmaps by shipping DOM content and interactions to Microsoft. In this
portal that DOM is client data: repo names, file paths, vulnerability details, finding snippets,
user emails. That is a data-protection decision (DPA/client NDAs; GDPR consent for EU users), not a
code one, and it needs sign-off before any script is added. It also would not answer the questions
asked here — "who is active in project X", "what did project Y do today" — which the first-party
activity data in section 5 answers exactly.

If UX analytics are still wanted after sign-off: load Clarity only when an admin enables it in
Workspace Settings, with masking mode **Strict** (all text masked), only on the unauthenticated
pages (login/register) or behind per-user consent, and add `clarity.ms` to the CSP. Estimated
size: one setting, one `<Script>` component, CSP entry.

## 8. Other additions worth considering (not in scope unless chosen)
1. **Scanner version drift alert** — CI pipelines running a scanner older than the latest published
   binary (data already on every cicd scan).
2. **Failure-spike alert** — a project whose failure rate in the last 24h exceeds N% notifies admins
   immediately rather than waiting for the digest.
3. **Quota 80% notice** to the project owner, through the existing notification catalog.
4. **Stale projects** — no scan in 30 days, listed in the digest.

## 9. Failure alerts routed to multiple webhooks

**Trigger.** On 2026-10-28 CI pipelines could not download the scanner (a `ScannerBinary` row
outlived its GridFS file — fixed in 95194da, which also added `scanner.binary_missing`). The ask:
any failure like that, or a scan the portal fails, reaches Teams — and different kinds of alert can
go to different channels.

**What the portal can and cannot see.** A pipeline that reaches the portal and fails leaves a
trace (a failed download request, a cicd scan stuck `pending`, a scan marked `failed`). A pipeline
that never reaches the portal (runner offline, DNS, firewall) leaves none; the only portal-side
signal is *silence*, covered by `pipeline.silent` below. The CI system's own failure notification
remains the backstop for that case.

**New events** in `core/notification_events.py` (all `audience="admin"` unless stated):
| Key | Fires when | Dedupe |
|---|---|---|
| `scanner.download_failed` | `GET /downloads/zerostrike/...` returns non-2xx: unknown version, no binary for that os/arch, file missing (wraps `binary_missing`), checksum file missing | once per (version, os-arch, reason) per hour |
| `pipeline.upload_stalled` (project) | a cicd scan stays `pending`/`running` past `scan_timeout_seconds × queue_stuck_multiplier` — the pipeline created it and died | once per scan |
| `pipeline.silent` (project) | a project whose pipeline ran on ≥3 of the last 7 days has no cicd scan for 24h | once per project per day |
| `scan.failed` (existing, project) | cloud or cicd scan ends `failed` — card now carries scan type, stage, error message, repo/branch, CI build link | once per scan |
| `portal.error` | a backend log record at ERROR+ (already persisted by `core/log_sink`), grouped by logger + message fingerprint | once per fingerprint per hour |

Alerts must not alert about themselves: a webhook delivery failure is logged at WARNING and shown on
the channel's status, never re-emitted as `portal.error`.

**Webhook channels.** New collection `webhook_channels`: `{name, url_enc (encrypted, never
returned), enabled, events: [keys], project_ids: [] (empty = all projects), include_digest: bool,
last_delivery_at, last_status, last_error}`. Admin-only CRUD (`require_admin`, audited, URL vetted by
`alert_service.vet_webhook_url`), each with a **Send test** button. Routing lives in one place,
`notification_service.notify()`: after in-app/email delivery it posts to every enabled channel whose
`events` contain the key and whose `project_ids` match. Same contract as today: never raises.
- Migration: the current single `WorkspaceSettings.alert_webhook_enc` becomes a channel
  "Admin alerts" subscribed to every admin-audience event, so nothing that reaches Teams today stops.
- Per-project alert webhooks (`Project.alert_webhook_enc`, owner-managed) are untouched.
- Example routing: "#thinkshield-incidents" ← `scanner.*`, `portal.error`, `pipeline.*`;
  "#thinkshield-scans" ← `scan.failed` for selected projects; "#thinkshield-daily" ← digest only.

UI: the Control Panel's "Teams digest" tab becomes **Webhooks & alerts**: channel list (status dot
from last delivery), add/edit dialog with an event checklist grouped by area, project multi-select,
digest toggle; digest schedule settings sit under it.

## 10. New CVEs per project (digest column + Projects table)

"New CVE observed" = an advisory id (CVE or GHSA) on a dependency finding in the period that the
project had not reported before the period started. One aggregation over findings: ids in window
minus ids before window, grouped by project. Shown as a column in the digest and the Control Panel
Projects table: count, plus the newest 2 ids with severity (e.g. `3 · CVE-2026-1234 (H), GHSA-xxxx (C)`),
the full list behind a tooltip/expander. Source wording stays honest: these were found by OSV.dev
lookups during that project's scans — the portal does not hold a CVE feed.

## Defaults taken (2026-10-28; change before "go" if wrong)
- Digest: daily 09:00 IST (03:30 UTC); weekly selectable.
- Digest goes to channels with `include_digest`; the migrated "Admin alerts" channel starts with it off.
- Section 8 extras: quota 80% notice and stale-project list included (cheap); version-drift and
  failure-spike are covered by the digest's scanner block and `scan.failed`/`portal.error`.

## Build order when "go" is given
1. Activity collection + throttled writers + Control Panel Overview/people metrics (backend, tests).
2. Control Panel rename/tabs + Project activity tab (frontend).
3. Webhook channels + routing in `notify()` + migration + new events with dedupe.
4. Digest settings, card builder (pure function, unit-tested against a fixture) incl. new-CVE column,
   scheduler, test send.
5. Browser QA as admin + member; one live "Send test now" to the Teams channel, with the user's OK.

## API contract for Part 2 (fixed 2026-10-28, build started)

All under `/api/v1`, all `require_admin`. Datetimes are UTC ISO strings with offset.

**Overview / projects** — extend the existing `GET /admin/project-insights?since&until` response:
- top-level `users: {total, registered_in_window, registered_today, active_in_window, active_today,
  never_signed_in, pending_approval, disabled}` (`today` = current UTC day).
- each `projects[]` row gains `members: int`, `active_users: int` (distinct users with an activity
  day in window that includes this project), `new_cves: {count: int, latest: [{id: str, severity:
  str}]}` (latest ≤ 2, newest first).

**Project activity** — `GET /admin/project-insights/projects/{project_id}/activity?since&until&limit`
(limit ≤ 200, default 100) → `{project_id, name, active_users: [{user_id, email, name,
days_active, last_seen_at}], timeline: [{at, action, actor_type, actor_email, target_type,
target_id, metadata}]}` — timeline from the audit log for that project, newest first. 404 for an
unknown project. Requests & errors for one project reuse `/admin/project-insights/requests?project_id=`.

**Webhook channels**
- `GET /admin/webhook-channels/events` → `[{key, label, description, audience, group}]` (every
  event in the catalog plus `digest` is NOT an event — it is the `include_digest` flag).
- `GET /admin/webhook-channels` → `[Channel]`; `POST` body `{name, url, enabled=true, events=[],
  project_ids=[], include_digest=false}` → `Channel` (201); `PATCH /{id}` same fields all optional
  (`url` omitted = unchanged) → `Channel`; `DELETE /{id}` → 204; `POST /{id}/test` → `{ok: bool,
  status: int|null, error: str|null}`.
- `Channel = {id, name, url_host, enabled, events, project_ids, include_digest, last_delivery_at,
  last_status: "ok"|"error"|null, last_error, created_at}` — the URL itself is never returned.
- Unknown event keys → 422. URL rejected by `vet_webhook_url` → 422 with its message.

**Digest**
- `GET /admin/digest-settings` / `PUT` → `{enabled, frequency: "daily"|"weekly", hour_utc,
  minute_utc, weekday (0=Mon, weekly only), project_ids: [] (empty = all), include_stale_projects,
  last_sent_at, last_status, last_error}` (PUT ignores the `last_*` fields). Default: disabled,
  daily, 03:30 UTC (09:00 IST).
- `GET /admin/digest-settings/preview` → `{period_start, period_end, rows: [{project_id, name,
  pipeline_runs, pipeline_failed, cloud_scans, cloud_failed, critical, high, quota_used,
  quota_limit, new_cves: {count, latest}}], totals: {same numeric fields}, scanner: {engine_available,
  backend_scanner_version, latest_binary_version, outdated_ci_runners: int, rule_pack_version,
  rule_count, osv_reachable: bool, new_cve_ids: [..≤5]}, stale_projects: [{project_id, name,
  last_scan_at}], quota_warnings: [{project_id, name, used, limit}]}`.
- `POST /admin/digest-settings/send-test` → `{sent: int, errors: [{channel_id, name, error}]}` —
  posts the current digest to every enabled `include_digest` channel.

Frontend: `/admin/control-panel?tab=overview|projects|activity|requests|webhooks` (activity also
takes `&project=<id>`); `/admin/project-insights` redirects there; nav label "Control Panel".

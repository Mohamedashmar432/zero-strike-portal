# Live dependency advisory alerts (plan, 2026-10-30)

Planned by Opus 5.5, built by Sonnet 5.5, tested by Haiku 5.5. This is the decision record the build follows.
Where this doc and the code disagree later, the code wins.

## 1. Goal

When an advisory (CVE/GHSA/PYSEC/GO/MAL) is **published in the last 72 hours** and a package it affects is
**in a project's dependency inventory**, alert that project once, with the impact ("released <UTC time>, your
project uses `pkg@version`, fix `x`"). Never re-alert old vulnerable dependencies daily: only newly arrived
advisories that actually match. Delivery: the project's own alert webhook and mailboxes, webhook channels
subscribed to the new event, and project members per their in-app/email preference.

## 2. What the code said (verified 2026-10-30)

- **The portal has no full dependency list.** Only `Finding.dependency` for already-vulnerable packages. The
  Go scanner (`internal/scanner/sca/scanner.go`) parses every manifest into `[]Dependency{Ecosystem, Package,
  Version, Manifest, Direct}` and then **throws the list away**; the JSON report has no inventory.
  `GoReportIn` uses `extra="ignore"`, so a new top-level key is dropped by the parser but kept in
  `Report.raw_json`.
- Ecosystems the scanner parses: `npm`, `PyPI`, `Go`, `Maven`, `NuGet`. yarn/pnpm parsers mark every entry
  `Direct: true` (unreliable), so a card must not overstate "direct" for those manifests.
- The scanner calls OSV `querybatch` and `vulns/{id}`. Severity: `database_specific.severity`, else highest
  CVSS_V3 base score from the vector, else medium. Dependency fingerprint:
  `sha256(eco|package|primary)[:16]`, `primary` = GHSA if present else the smallest id (`representativeID`).
- OSV has no "published today" query. The GCS bucket does: `https://osv-vulnerabilities.storage.googleapis.com/
  <ECO>/modified_id.csv` (`<RFC3339 modified>,<ID>`, newest first; HTTP Range works) and records at
  `<ECO>/<ID>.json` (fields `published`, `modified`, `aliases`, `affected[]`, `database_specific.severity`).
  A 256 KB head covers more than 24 h per ecosystem. Last 24 h on 2026-10-30: npm 227 rows (217 `MAL-`), PyPI
  157, Go 4, Maven 10, NuGet 0. An old advisory being **modified** is common and must not alert.

## 3. Architecture (decisions)

1. **Inventory: the scanner emits it** (new top-level `Dependencies` array in the JSON report, no `Severity`
   field because customers' CI gates grep `^      "Severity"` at six spaces). The portal stores one snapshot
   per (project, repo scope), replaced on every ingest that carries the key; absent key = leave the previous
   snapshot alone (old scanners degrade to "no inventory yet"). Rejected: portal-side lockfile parsing (duplicate
   parsers, cloud only), re-deriving from findings (misses the main case: a clean package that becomes
   vulnerable today). Existing projects get an inventory on their next scan.
2. **"Released" source: OSV GCS `modified_id.csv` per ecosystem**, read with Range requests and a per-ecosystem
   `modified` cursor; record `published` decides newness. Rejected: querybatch polling of every dependency,
   GitHub Advisory API (token, limits), NVD (no package data), KEV/EPSS (v2).
3. **Matching: candidates by index, confirmed by OSV's own matcher.** Candidate = inventory dep whose
   `eco|normalised name` key hits. Confirmed locally only if the version is in the record's explicit `versions`;
   every other candidate goes in ONE querybatch call (only `(ecosystem, package, version)` triples, the same data
   the scanner already sends). No home-grown range matching.
4. **Scheduler: a new lifespan task `live_alert_service.watch_loop()`**, not riding the scan queue or digest
   loop. Wakes every 60 s, runs when due (default every 60 min) under an atomic lease on a singleton.
5. **Two events:** `dependency.new_advisory` (audience project, in-app + email default on) and
   `advisories.feed_unreachable` (audience admin).
6. **Delivery per project per run: one grouped message.** `notify()` (channels + members) and a new
   `alert_service.send_project_live_alert()` (the project's own webhook + mailboxes, no new `alert_triggers`
   value). No Finding/Vulnerability row is created (they belong to a scan and drive counters, compliance and the
   CI gate); the ledger is the record and the next scan turns it into a real finding.
7. **Settings:** `WorkspaceSettings` (admin-only): `live_alerts_enabled` (default **True**),
   `live_alerts_min_severity` (default **high**), `live_alerts_include_malicious` (default **True**).
   `Project.live_alert_min_severity` (`critical|high|medium|off|None`) may only **tighten**; resolved in
   `effective_live_alert_policy`. Operations knobs live in `core/config.py`, not the UI.

User decisions taken as the recommended defaults: workspace default on; `MAL-*` malicious reports included and
rated critical; "released today" = rolling 72 h on `published` with the exact UTC time on the card; threshold
High and Critical; the project's own webhook/email receive it without a new tick-box (Off is the opt-out).

## 4. Data model

`models/dependency_inventory.py`, collection `dependency_inventories`: `project_id`, `repo_scope_key`
(`repo_key_resolver`), `project_repo_id`, `repo_label`, `scan_id`, `scan_type`, `git_commit`, `branch`,
`scanner_version`, `scanned_at`, `dep_count`, `truncated` (>20,000), `deps: list[InventoryDep]`, `updated_at`.
`InventoryDep{k: "<eco>|<normalised name>", ecosystem, package, version, manifests (<=10, repo-relative),
direct}`. Indexes: unique `(project_id, repo_scope_key)`, multikey `deps.k`, `project_id`.

`models/live_dependency_alert.py`, collection `live_dependency_alerts` (the dedupe ledger, the in-portal feed and
the delivery record): `project_id`, `advisory_id` (representative id), `advisory_ids` (id + aliases), `summary`
(<=200), `ecosystem`, `package`, `package_norm`, `version`, `severity` (`critical|high|medium|low`),
`cvss_score`, `malicious`, `published_at`, `modified_at`, `fixed_versions` (<=3), `locations: list[AlertLocation
{repo_scope_key, repo_label, manifests (<=5), direct, inventory_scan_id, inventory_scanned_at, git_commit}]`,
`run_id`, `created_at`, `delivery: {channels, in_app, project_webhook: sent|failed|off, project_email:
sent|failed|not_configured|off}`. Indexes: **unique `(project_id, ecosystem, package_norm, version,
advisory_id)`**, `(project_id, created_at -1)`, `(created_at -1)`, TTL `created_at` 400 days.

`models/advisory_watch_state.py`, singleton `advisory_watch_state`: `cursors: dict[eco, datetime|None]`,
`lease_owner`, `lease_until`, `last_run_started_at`, `last_run_finished_at`, `last_success_at`,
`last_status: ok|partial|error`, `last_error`, `consecutive_failures`, `failing_since`, `unreachable_alerted_at`,
`last_gap_at`, `last_gap_hours`, `last_advisory_id`, `last_advisory_published_at`, `last_run_summary: dict`,
`updated_at`. Register all three in `app/db/mongo.py`.

`core/config.py`: `advisory_watch_enabled=True` (environment kill switch), `advisory_watch_interval_minutes=60`
(min 15), `advisory_max_age_hours=72`, `advisory_catchup_hours=72`, `advisory_settle_minutes=10`,
`advisory_max_records_per_run=1000`, `advisory_feed_unreachable_alert_hours=6`,
`live_alert_inventory_max_age_days=180`, `advisory_feed_base_url`, `osv_api_base_url` (the last two default to the
fixed OSV hosts; the production validator rejects any other value, overrides only when `app_env=="development"`:
the SSRF guard).

## 5. Modules and signatures

`core/advisory.py` (pure, no I/O): `SUPPORTED_ECOSYSTEMS`, `AffectedPkg`, `Advisory`,
`parse_modified_csv(text, *, drop_partial_tail)`, `normalize_package_name(eco, name)` (lower; PyPI PEP 503
`[-_.]+`->`-`), `dep_key`, `representative_id(ids)` (port of osv.go), `sca_fingerprint(eco, package, primary_id)`,
`cvss3_base_score(vector)` (port of osv.go), `derive_severity(record)` (`MAL-*` or malicious origins ->
critical; else label; else highest CVSS_V3 from top level and `affected[].severity`; else medium; v2/v4 vectors
alone give medium), `normalize_advisory(record, ecosystem)`, `is_new(adv, now, max_age)` (published set, not
withdrawn, `now-max_age <= published <= now`), `severity_meets(sev, minimum)` ("off" never meets), `stricter(a,
b)`, `build_alert(project_name, project_id, rows, now) -> AlertMessage(title, text, facts, link,
notif_severity)`.

`services/advisory_feed_service.py` (I/O, fixed hosts, `httpx.AsyncClient(timeout=10, follow_redirects=False)`):
`fetch_rows_since(eco, cursor, horizon)` (256 KB Range chunks, <=8, carries a partial line across chunks, returns
`(rows, reached_cursor)`), `head_modified(eco)`, `fetch_record(eco, id)` (None on 404, raises otherwise; ids
validated against `^[A-Za-z0-9._:-]{1,80}$`), `confirm(pairs)` (querybatch chunks of 500, follows
`next_page_token` <=3, returns ids per pair). Internal `_get`/`_post` are what tests stub.

`services/dependency_inventory_service.py`: `build_snapshot(scan, report, scope_key, repo_label)` (pure: merge by
(eco, pkg, version), normalise manifests, cap 20k), `upsert_from_report(scan, report)` (never raises),
`coverage()`. Hook in `report_ingestion_service.ingest()` after the Report insert and before reconcile, in
try/except with a warning log.

`services/live_alert_service.py`: `run_once(*, now=None, force=False, dry_run=False) -> RunSummary`,
`watch_loop()`, `status()`, `project_feed(project_id, limit=50)`; private `_claim_lease`, `_release`,
`_process_ecosystem`, `_match`, `_claim_alert`, `_deliver`, `_feed_health`.

Also: `alert_service._safe_webhook/_safe_emails` return their outcome; add
`send_project_live_alert(project, title, text, link, facts) -> (webhook_outcome, email_outcome)` (bypasses
`alert_triggers`; `"off"`/`"not_configured"` without sending); `workspace_settings_service.
effective_live_alert_policy(project)`; the two events in `core/notification_events.py`; `"new_advisory"` and
`"unreachable"` in `webhook_channel_service._BAD`; `main.py` creates/cancels the watch task beside `digest_task`;
`tests/conftest.py` autouse stubs `advisory_feed_service._get/_post` to raise ("tests never reach OSV").

## 6. Algorithm (`run_once`)

1. Workspace disabled and not a dry run -> `skipped`.
2. **Lease:** `find_one_and_update` on the singleton (upsert) with `lease_until` null or past AND (force or
   `last_run_started_at` null or older than the interval); set `lease_owner=run_id`, `lease_until=now+15min`,
   `last_run_started_at=now`. No document back -> `busy`. Every later state write is conditioned on
   `lease_owner == run_id`.
3. For each ecosystem (an exception marks the run `partial`, leaves that cursor alone, continues):
4. **First run never backfills:** cursor None -> `head_modified(eco) or now`; alert nothing. Turning the workspace
   toggle on resets all cursors to None.
5. **Catch-up cap:** `floor = now - catchup_hours`; cursor older than the floor -> set `last_gap_*`, cursor =
   floor, audit `Advisory Watch Gap Skipped`.
6. `horizon = now - settle_minutes`; `fetch_rows_since`; not `reached` after 8 chunks -> record a gap.
7. Sort ascending by modified, keep `max_records_per_run`, fetch records with a semaphore of 8. 404 -> skip;
   other error -> stop the ecosystem there (cursor advances only to the last good row).
8. **Qualify:** not withdrawn; `is_new`; severity meets the workspace minimum (or malicious and included); has an
   affected entry in this ecosystem.
9. **Candidates:** one query `DependencyInventory.find({"deps.k": {"$in": keys}})`; drop archived/missing
   projects and inventories older than `live_alert_inventory_max_age_days`.
10. **Confirm:** explicit version match, else one `confirm()` for the unique remaining triples (confirmed iff
    returned ids intersect `adv.ids`). A `confirm()` failure raises for this ecosystem: cursor unchanged, next
    tick retries; the ledger prevents a double alert.
11. Per confirmed (project, advisory, dep), group locations by project: (a) apply the project's effective policy;
    (b) skip if a scan already reported it (`Finding` with `project_id`, `kind="sca"`, `dependency.package`,
    `dependency.advisory_ids $in adv.ids`); (c) skip if an accepted exemption exists (`Vulnerability` with
    `fingerprint=sca_fingerprint(eco, package, adv.rep_id)`, `review.status="accepted"`); (d) skip if a ledger
    row already has the same (project, ecosystem, package_norm, version) and any alias; (e) unless dry run insert
    the ledger row (merge locations across repos), `DuplicateKeyError` -> skip. Claim-then-deliver = at most once.
    Advance `cursors[eco]` to the max modified processed, conditioned on the lease.
12. **Deliver** per project: `build_alert`; `notify("dependency.new_advisory", ...)`; `send_project_live_alert`;
    write `delivery`; audit `Live Dependency Alert Raised` (system actor, project-scoped, advisory ids/packages/
    counts only, never URLs or addresses).
13. **Feed health:** success -> `last_success_at`, reset failures, clear `failing_since`/`unreachable_alerted_at`.
    All ecosystems failing on fetch -> `failing_since`, `consecutive_failures++`; after
    `advisory_feed_unreachable_alert_hours`, atomically claim `unreachable_alerted_at` and `notify(
    "advisories.feed_unreachable")` to admins once per outage + audit `Advisory Watch Failed`. A failure never
    alerts a project and never moves a cursor past unprocessed rows.
14. Release the lease in `finally`. `watch_loop` logs at WARNING only (ERROR triggers `portal.error`).

Rules that follow: NEW = published within 72 h AND no ledger row for (project, ecosystem, package, version, any
alias) AND no scan already reported it. A dependency added later that is vulnerable to an *old* advisory is the
findings flow, not this alert. A widened range alerts only for newly matching versions, only within 72 h of
publication.

## 7. Alert content

Title: one advisory `"{Project}: new {CRITICAL|HIGH} advisory in {package} {version}"`, several
`"{Project}: {N} new dependency advisories ({c} critical, {h} high)"`. Body: `Published <d Mon YYYY HH:MM> UTC
(<h>h ago) on OSV.dev. Your latest scan of this project uses an affected version.` / `Inventory as of scan
<date>, commit <sha7>.` / `Rescan to track it as a finding.` Facts (max 12): `Released`, `Project`, per advisory
(max 5, worst then newest): `("<rep_id> · <first CVE alias>", "<SEV> <cvss> · <package> <version> -> fix
<fixed[0] or 'none yet'> · direct|transitive · <k> repo(s): <labels[:2]> · <manifest[0]>")` (malicious:
`MALICIOUS PACKAGE · remove <package> <version>`; yarn/pnpm manifests say "declared in"), `More`, `Details`
(`https://osv.dev/vulnerability/<rep_id>` for a single advisory). Link `/projects/{id}?tab=overview&src=alert`.
Never include the advisory `details` text in a webhook. Card budget: `json.dumps(card) < 12 KB` with 20
advisories (tested). `notif_severity`: critical/malicious -> `error`, else `warning`. Email: members via
`notify`; project mailboxes via `send_project_live_alert`; `smtp_host` unset -> record `not_configured` without
attempting; a failure records `failed` (prod SMTP currently returns 525) and the UI never says "sent" unless the
outcome recorded it.

## 8. API and frontend

Admin `routers/admin_live_alerts.py` (`/admin/live-alerts`, `require_admin`): `GET ""` -> `LiveAlertStatus`
(enabled, min_severity, include_malicious, server_watch_enabled, interval_minutes, max_age_hours, last_* health,
`ecosystems[{ecosystem, cursor, lag_minutes}]`, `last_advisory_*`, `last_run_summary`, `coverage{projects_active,
projects_with_inventory, inventories_cloud, inventories_cicd, oldest_inventory_at}`, `email_delivery_configured`,
`recent[20]`); `PUT ""` `{enabled?, min_severity?, include_malicious?}` (audit `Live Alert Settings Changed`;
false->true on `enabled` resets cursors); `POST "/run"?dry_run=` -> `{status: ran|busy|skipped, summary,
previews[{project_id, project_name, card, bytes}]}` (force; 409 when busy; a dry run claims nothing, advances no
cursor, delivers nothing; audit `Live Alert Check Triggered`).

Project: `routers/alerts.py` response gains `live_alert_min_severity`, `live_alert_effective`,
`workspace_live_alert_min_severity`; update request gains `live_alert_min_severity` (`"inherit"` -> None), under
the existing owner/admin guard; looser-than-workspace values are stored but resolved tighter and the UI disables
them. `GET /projects/{id}/live-alerts` (member): `{effective_min_severity, enabled, inventories[{repo_label,
scan_type, scanned_at, git_commit, dep_count, scanner_version, truncated}], alerts[LiveAlertRow],
email_delivery_configured}`.

Frontend: `lib/api/live-alerts.ts` (+ `query-keys.ts`, `alerts.ts`), `components/control-panel/
live-alerts-section.tsx` in `webhooks-tab.tsx` after `DigestSection` (switch, min severity, malicious switch,
Check now, Preview, status line, per-ecosystem lag, coverage "N of M active projects have a dependency
inventory", recent table, email-not-configured notice, 409 toast), `components/alerts/alert-cards.tsx` select
(Inherit / Critical only / High and above / Medium and above / Off; looser options disabled with "A project can
only tighten the workspace setting."), `components/projects/live-alerts-card.tsx` on the project Overview
(delivery chips; inventory line per repo or "No dependency inventory yet - runs after the next scan with scanner
>= vX.Y"). Settings > Notifications lists the new event from the catalog.

## 9. Tests

`tests/test_advisory_core.py` (pure; synthetic package names like `example-widget`, never client data;
fixtures under `tests/fixtures/osv/`): modified-csv parsing with a partial tail, PEP 503 normalisation, GHSA
preferred as representative id, fingerprint golden value from the Go formula, CVSS golden vectors (9.8, 7.5,
5.3), severity precedence, malicious = critical, old-published-recently-modified is not new, withdrawn is not
new, a project cannot loosen, card budget with 20 rows, Released line / fix / links present.
`tests/test_live_alerts.py` (mongomock, a `FakeFeed` stub): inventory upsert from a report with
`Dependencies`; a report without the key keeps the previous inventory; empty list replaces it; first run sets
cursors and alerts nothing; new advisory matching an inventory alerts once, grouped per project; second run does
not re-alert; an alias from another database does not re-alert; old advisory modified today does not alert; a
widened range alerts only the new version; already reported by a scan is skipped; accepted exemption suppresses;
archived project and stale inventory skipped; project without inventory ignored; multi-ecosystem in one run;
querybatch failure leaves the cursor and retries; record-fetch error advances only to the last good row;
downtime beyond the catch-up clamps the cursor and records a gap; project threshold filters; disabling then
re-enabling resets cursors (no backfill); two concurrent `run_once` -> exactly one `ran`; expired lease is
reclaimable and a stale owner cannot move the cursor; feed unreachable alerts admins once after the threshold
and resets on success; dry run claims nothing and returns previews; routes to a subscribed channel and the
project webhook; email not configured recorded honestly; delivery failure logs WARNING not ERROR; audit rows are
system-actor and project-scoped. `tests/test_live_alerts_api.py`: members refused on admin routes; run returns
409 when busy; project feed needs membership; an owner's looser value resolves to the workspace minimum;
notification catalog exposes the member event to members and the admin event only to admins.

Real e2e (QA agent, local only, never real Teams): build the scanner, run a cloud scan and confirm the
inventory row's `dep_count` equals the report's `Dependencies` length, then upload a CI report and confirm its
scope row; run a local OSV stub (`python -I http.server`, GCS-shaped `npm/modified_id.csv`,
`npm/GHSA-test-qa1.json` naming a package@version that is in the dev inventory with `published` = now-1h,
`v1/querybatch`), backend started with `APP_ENV=development ADVISORY_FEED_BASE_URL=http://127.0.0.1:8765/
OSV_API_BASE_URL=http://127.0.0.1:8765/`: first run alerts nothing; add the row; dry run -> one preview under
12 KB; real run -> one ledger row, an in-app notification, audit row `Live Dependency Alert Raised`
(`actor_type=system`), `project_email=not_configured`; second run no new row; a 10-day-old `published` record
does not alert; stop the stub, run 3 times with `ADVISORY_FEED_UNREACHABLE_ALERT_HOURS=0` -> exactly one
feed-unreachable admin notification; restart -> `last_status=ok`. Then browser QA per CLAUDE.md as admin and
member (wire-level request bodies, refusal paths, zero console errors).

## 10. Build order

M1 scanner: emit `Dependencies` (`SCAScanner.Inventory()`, `report.Report.Dependencies []DependencyRef{Ecosystem,
Package, Version, Manifest, Direct}` with no `Severity` field, populated in `cmd/zerostrike/scan.go` when
`--enable-sca`, nil otherwise; extend `TestReportLayoutContract`; a test that inventory equals parsed deps and is
null without SCA). Release/publish is a separate step. M2 portal: inventory ingestion. M3: the pure core and
fixtures. M4: the run engine, models, config, policy, events, conftest stub, lifespan wiring. M5: API and
frontend. M6: e2e and docs.

Rollout: existing projects cannot be backfilled (old reports carry no inventory); coverage grows on the next scan
(CI on its next pipeline run with the `latest` scanner, cloud scans after the image rebuild); the Control Panel
coverage line shows it. `ADVISORY_WATCH_ENABLED=false` is the feature flag.

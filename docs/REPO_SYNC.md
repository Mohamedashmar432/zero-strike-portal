# Repo Sync

Status: design, build in progress on `feat/repo-sync`. Date: 2026-10-04.

## 1. Problem

A developer fixes findings and pushes. The portal's picture of the repo (latest scanned commit,
open findings, dashboard counts, compliance posture) stays at the last scan until someone rescans.
"Sync" brings one connected repo up to its remote branch head and shows what was fixed, what is
still open and what is new, with the commit/branch each change was observed in.

## 2. What already exists (do not rebuild)

- `services/vulnerability_service.reconcile_scan` (see `docs/VULNERABILITY_LIFECYCLE.md`) is the
  finding-diff engine: per (project, repo scope, fingerprint) it creates, refreshes, reopens and
  resolves `Vulnerability` rows. Guards already in place: no "fixed" without a prior completed scan
  of the scope, out-of-order scans never rewind posture, absence only counts for analyzer kinds the
  scan ran, idempotent re-ingest, dispositional resolutions never overturned.
- `GET /projects/{id}/scans/{scan_id}/regression` returns new/unchanged/reopened/fixed counts.
- Dashboard, compliance and reports use the latest completed scan per repo, so a completed sync
  scan propagates everywhere with no extra wiring.
- A failed or reaped cloud scan never reaches `report_ingestion_service.ingest()`, so a failure
  can never mark anything fixed.

Missing: remote head commit, a cheap "anything new?" check, commit/branch attribution on lifecycle
transitions, a sync trigger with double-sync protection, and UI.

## 3. What "sync" means

Sync = `git ls-remote` for the repo's `selected_branch`. If the latest completed scan of that repo
already covers that commit on that branch, return `up_to_date` and do nothing. Otherwise enqueue a
normal cloud scan (`triggered_by="sync"`) through the existing queue; the diff happens inside the
existing `reconcile_scan` when it ingests. `force=true` bypasses the short circuit ("Rescan anyway").

Rejected: ls-remote only (cannot say what was fixed); incremental scan (scanner is whole-tree, clone
is depth 1); a new worker/queue (the Mongo queue already provides caps, reaping, SSRF, token handling).
Cost: ls-remote is one small round trip; a sync scan costs what a manual cloud scan costs and adds
no new LLM spend path.

## 4. Fingerprint stability (scanner `internal/findings/builder.go`)

| Kind | Input | Survives line move | Survives file rename |
|---|---|---|---|
| sast | rule, enclosing function, normalized snippet | yes | yes |
| secret | detector, hash of secret prefix | yes | yes |
| sca | ecosystem, package, advisory | n/a | yes |
| config | rule, config_file, key | yes | no |

Editing the vulnerable line while still vulnerable, or renaming a config file, reads as
fixed + new. UI wording is "Fixed (no longer detected)" with a tooltip explaining this.

**Config-fingerprint scanner dependency.** Config fingerprints depend on the scanner's `config_file`
and `key` inputs being stable between scans. A scanner release that changes how those are derived
(path normalization, key naming) makes every config finding read as fixed + new on the next sync,
and the portal cannot detect this. Scanner upgrades that touch config fingerprinting need a
coordinated note here; the scanner-version-changed flag in the sync summary is the only signal.

## 5. Data model (additive, nullable, no migration)

- `ProjectRepo`: `remote_head_sha`, `remote_head_checked_at`, `last_sync_error`, `sync_lease_until`.
  Clear head/error fields when `selected_branch` changes.
- `Scan.triggered_by` gains `"sync"` (mirror in `schemas/scan.py`, `frontend/lib/api/scans.ts`).
- `Vulnerability`: `first_seen_commit/branch/scan_id` (insert only), `last_seen_commit`,
  `fixed_commit/branch/scan_id` (fixed timestamp reuses `resolved_at`), `reopened_commit`
  (reopen clears `fixed_*`).
- Derived `fix_status` on `VulnerabilityOut`: `fixed` (resolved, reason fixed), `reopened`
  (open/in_progress with `reopened_at`), `dismissed` (other resolutions, accepted_risk), else `open`.

## 6. Diff changes and edge cases

1. In `ingest()`, assign scan `git_commit`/`branch`/scanner_version above the reconcile call
   (currently after it, so reconcile never sees them).
2. `cloud_scan_service`: after clone run `git rev-parse HEAD` and set `scan.git_commit` if empty.
3. Stamp first_seen / last_seen / fixed / reopened commit+branch in reconcile; add to audit metadata.
4. Branch-switch guard: if baseline scan branch differs from this scan's, `detect_fixed=False`
   for the run; return `baseline_branch_mismatch`.
5. Unanalyzed-file guard: error diagnostics with a file keep that file's vulnerabilities open.
6. Return `ReconciliationResult` from `ingest()` for notification counts.

| Case | Behavior |
|---|---|
| First sync | "Baseline established at abc1234", not "0 fixed" |
| Scan fails | Never ingests; repo row shows Error; vulnerabilities untouched |
| ls-remote fails | No scan; `last_sync_error` set; readable 409 |
| Head unchanged | `up_to_date`; a failed/legacy-commitless last scan is never "up to date" |
| Force-push | States compared, not ancestry; works |
| Branch switched | Guard 4: first scan on new branch fixes nothing |
| Old branch findings after a switch | By design they stay open: the first scan on the new branch fixes nothing (guard 4), so findings seen only on the old branch are neither fixed nor closed. They resolve if the repo is switched back and rescanned, or by hand |
| Scanner upgraded | Not suppressed; summary notes version change |
| Auto-fix PR merged | Next sync marks fixed with merge commit; phase 6 adds PR link |

## 7. API (portal JWT only)

`POST /api/v1/projects/{project_id}/repos/{repo_id}/sync`, body `{force: bool=false}`, `require_member`,
archived project 409. `services/repo_sync_service.sync_repo`: rate limit; atomic 90s lease on
`ProjectRepo` (409 if held); if a queued/running scan exists return `already_syncing`; `ls-remote`
via `git_workspace.remote_head` (SSRF-validated, token via `GIT_CONFIG_*` env never argv, branch name
validated, timeout, sanitized errors); persist head; unchanged and not force -> `up_to_date`;
else `scan_service.enqueue_repo_scan(..., triggered_by="sync")` (factored out of `create_scan`) -> 202
`scan_queued`. Response: `{outcome, scan_id, remote_head_sha, repo}`.

`GET /projects/{id}/repos` gains `remote_head_sha`, `scanned_commit`, `scanned_branch`,
`last_synced_at`, `active_scan_id`, `last_sync_error`, derived `sync_state`
(`syncing|up_to_date|behind|error|never|unknown`).

`GET /projects/{id}/vulnerabilities/summary?repo=` returns open/in_progress/reopened/fixed/dismissed
and per-repo counts. `GET .../vulnerabilities` gains `fix_status` filter and commit fields.
Regression gains commit/baseline/mismatch/scanner-changed fields.

Audit: "Repo Sync Requested", "Repo Sync Failed" (project category). No new notification event; the
existing `scan.completed` for sync scans carries "N fixed, M new, K reopened, J still open".

## 8. Frontend (Signal Room; neutral badges, severity colors reserved for severity)

Repos tab rows: Repo | Provider | Branch | Head (sha7, `scanned -> remote` when behind) | Last synced |
Open / Fixed (links to filtered vulnerabilities) | Sync button. States: idle, syncing (spinner, poll),
up to date (toast with "Rescan anyway" -> `force:true`), behind, error (tooltip, "Retry"). On finish
invalidate repos, vulnerabilities, stats, scans; toast with counts. Sync replaces the row Scan button.

Vulnerabilities: "Introduced" (`branch@sha7`) and "Fixed in" columns, `fix_status` and repo filters,
commit line on detail. Project overview: Open / Reopened / Fixed card. Scan history shows "Sync" and
sha; regression section shows commit range and mismatch/scanner-change notices.

## 9. Build phases (each ends with pytest, ruff, tsc, lint)

1. Commit attribution in reconcile + ordering fix + guards (backend, tests in
   `test_vulnerability_reconcile.py`, `test_cloud_scan_service.py`).
2. `git_workspace.remote_head`, model fields, `enqueue_repo_scan`, sync endpoint (`tests/test_repo_sync.py`).
3. Repo `sync_state`, summary endpoint, `fix_status` filter, notification copy.
4. Repos tab Sync UX + browser QA per CLAUDE.md.
5. Vulnerabilities table/filters, overview card, history, regression UI + browser QA.
6. Optional: auto-fix skips already-fixed findings on superseded scans; "Fixed via auto-fix PR" link;
   backfill of legacy rows; PDF commit/branch.

## 10. Decisions / open questions

Defaults taken: Sync replaces the per-row Scan button; no dedicated notification type; phase 6 deferred.
Open: sandbox repo the QA tester can push to for end-to-end fix verification.

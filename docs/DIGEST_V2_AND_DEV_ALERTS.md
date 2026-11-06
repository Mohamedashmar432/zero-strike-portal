# Digest v2, per-project digest, and developer alerts

Status: planned 2026-11-03. Supersedes the card layout in `PROJECT_INSIGHTS_AND_CLOUD_SCAN_QUOTA.md`
section 6 (the scheduling, slot claim and multi-card posting rules there still hold).

## 1. Card 1 - Scanner (replaces "Scanner health")

Remove the "CVE data (OSV.dev)" section and the new-advisory list entirely. The card holds:

FactSet:
- Scanner in backend (`settings.scanner_build_ref`)
- Latest published binary (newest `ScannerBinary` by `uploaded_at`)
- Projects on an older scanner: N distinct projects (see table)
- New CVEs added: raw count (the existing `new_advisory_count`: advisory ids first reported by any
  project's dependency findings in the period). Just the number, no list.
- Scan engine: Available / NOT AVAILABLE (kept: it is the one readiness fact that matters)

Table "Pipelines on an older scanner" (column-set grid, Adaptive Cards 1.4, no `Table` element):
CI/CD scans created inside the report period whose `scanner_version` (normalised, `v` stripped)
differs from the latest published binary, grouped by (project, repo, hostname).
Columns: Project | Repository | Scanner used | Runs | Last run (UTC). Worst-offender first (oldest
version, then most runs). Cap 15 rows, then "+N more". If no binary is published, the table is
replaced by a note saying so. If none are outdated: "Every pipeline in this period used vX".
This replaces `_outdated_ci_runners` (14-day lookback count).

Title: "Scanner ready" / "Scanner NOT ready" (engine availability only; OSV no longer decides it).

## 2. Card 2..n - Project status

Columns: Project | CI/CD | Cloud | Critical | High | Fail rate | Resolved | New findings
- CI/CD, Cloud: scans created in the period (failed count no longer inline).
- Critical, High: current exposure, unchanged (latest scan per repo).
- Fail rate: failed / total scans in period, as `NN%`; `-` when no scans.
- Resolved: all-time count of the project's `Vulnerability` rows with `status == "resolved"`, across
  every repo.
- New findings: `Vulnerability` rows with `first_seen_at` in the period.
Removed: Quota, New CVEs. Ranking unchanged in spirit (critical, high, failed, activity).

## 3. Last card - Summary

Exactly three KPIs for the period: CI/CD scans, Cloud scans, Failed scans. Nothing else (no
needs-attention box, no scanner facts). Keep the "Open Control Panel" action.

## 4. Per-project scheduled digest

Today a channel with `include_digest` and a non-empty `project_ids` gets the *global* digest,
which leaks every project's numbers into a project's channel. New routing, decided in
`send_digest`:
- `include_digest` and empty `project_ids` -> the global digest (cards 1-3).
- `include_digest` and non-empty `project_ids` -> one project card per listed (non-archived) project.

Project card: title = project name, period subtitle, KPIs/facts:
Total scans, CI/CD scans, Cloud scans, Failed scans (period), Resolved (all-time, same definition
as the table), False-positive rate.
False-positive rate = project vulnerabilities with `resolution_reason == "false_positive"` or an
accepted `review.kind == "false_positive"` / all project vulnerabilities; `-` when there are none.
Same slot claim, same scheduler: no new loop.

## 5. Live critical/high CVE alert (any time)

Already exists: `live_alert_service` + `dependency.new_advisory`, threshold
`live_alerts_min_severity` default `high`, delivered to subscribed channels and the project's own
webhook. Gap check only: each advisory fact must carry severity (+CVSS when known), the fixed
("patch") version or "no fix yet", and impact (the advisory summary, truncated). Add whatever is
missing in `core/advisory.py` `_fact_for`/message builder. No new event.

## 6. Developer alerts for technical failures (any time)

Already exists: `portal.error` fires on every ERROR/CRITICAL log row (deduped hourly, capped).
Gaps to close so SMTP, DB, scanner and unhandled errors actually reach it:
- Unhandled exceptions: a catch-all exception handler (or confirm uvicorn's `uvicorn.error` records
  reach `log_sink`) that logs at ERROR with request id, returns 500 JSON.
- SMTP: an SMTP send failure is logged at ERROR by the caller/`email_service` (not WARNING).
  "smtp_host unset" stays WARNING (it is configuration, not a failure).
- Scanner: scanner subprocess failure / missing binary already logs ERROR; confirm.
- DB: when Mongo is down, `notify()` cannot read channels, so the alert about the outage cannot
  be routed. `notification_service` keeps the last successfully loaded channel list in memory;
  `portal.error` falls back to it when the channel lookup raises. Add a Mongo ping to the scan
  queue's existing `poll_loop` that logs ERROR ("database unreachable") on failure.
The rule "an alert must not alert about itself" (WARNING for delivery failures) is unchanged.

## Not in scope

Project-owned webhooks (`Project.alert_webhook_enc`) do not receive the per-project digest; add a
project opt-in if wanted. No new collection, no new scheduler.

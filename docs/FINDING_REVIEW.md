# Finding review: admin-accepted exemptions from the CI gate

## Why this exists

Pipelines fail on critical/high findings in the scanner's local JSON report, counted by a `grep`
that lives in every customer's pipeline YAML (`frontend/lib/cicd/findings-gate.ts`). Marking a
finding as a false positive used to hide it only in the portal, so the next pipeline run failed on it
again; and any project member could make that call alone.

Now a member *requests* an exemption, a portal admin decides, and an accepted exemption stops the
finding counting in the portal **and** in the CI gate, with no change to anyone's YAML.

## Admin review is a workspace setting (default off)

`WorkspaceSettings.finding_review_required` (Settings > General > Finding review, `PUT
/api/v1/workspace-settings`, admin only, no project twin) decides whether a request needs an admin.

- **Off (default).** A member's request is accepted the moment it is made
  (`finding_review_service.request_review`): review status `accepted`, reviewed by the requester,
  comment "Auto-accepted: admin review is off", the finding resolved as false positive (or
  accepted risk) and exempt from the next scan. Audit row `Finding Review Auto-Accepted`. The
  requester is notified (`finding.review_decided`); no admin is. The row appears on Finding Reviews
  as accepted and an admin can still revoke it.
- **On.** Everything below: the request stays pending, the finding keeps blocking, an admin decides.

Flipping the setting never rewrites history: pending requests stay pending (admins still decide
them) and accepted exemptions stay accepted. Acceptance side effects live in one helper
(`_apply_acceptance`) shared by auto-accept and an admin's `decide`.

## The workflow (when review is required)

| Finding kind | What a member may request | Effect while pending |
|---|---|---|
| Code (SAST, secret, config) | False positive (comment required) | None: still open, still blocks CI |
| Dependency (SCA) | Accepted risk (comment required). False positive is refused (422): a published advisory against the installed version is almost never wrong | None |

A portal admin (`User.role == "admin"`) accepts or rejects (rejecting needs a comment) on
**Administration > Finding Reviews**, and can later revoke an acceptance (comment required), which
reopens the finding so the next run blocks again. Admins may approve their own request; the audit
row records `self_approved: true`. Accepted exemptions never expire; they end on revoke, or when the
code changes enough to change the fingerprint.

Every step writes an audit row (`Finding Review Requested / Accepted / Rejected / Revoked / Migrated`)
and a notification (`finding.review_requested` to admins, `finding.review_decided` to the requester).

## What "exempt" means, exactly

An exemption is **(fingerprint, repo-relative file)**, scoped to one project and repo scope. The
fingerprint has no path in it (SAST: rule + enclosing function + snippet), so matching it alone
would also silence an identical snippet in another file. A moved or renamed file therefore needs a
new review.

`finding_review_service.accepted_exemptions(project_id, repo_scope_key)` is the single source both
consumers read, so the portal and the pipeline cannot disagree:

1. **Portal counts.** `report_ingestion_service._apply_suppression` marks matching findings
   `suppressed` with `suppressed_reason` `false_positive` or `accepted_risk`. They are stored and shown
   under "Show suppressed", never counted.
2. **CI gate.** `POST /api/v1/scans` (scanner create-scan) returns `accepted_exemptions`. The scanner
   (v0.40.0+) moves matching findings from `Findings` into a new `AcceptedExemptions` section of its
   report, leaves them out of `Stats` and the exit code, and prints
   `thinkShield: N finding(s) accepted by a portal admin ... reported, not counted`.

## Why no pipeline YAML changes

- Every pipeline downloads the `latest` scanner on each run, so a scanner release reaches all of them.
- YAML pipelines run the scanner with `--server/--token`; it calls create-scan before scanning and
  gets the list in the response. Older scanners ignore the field.
- Azure DevOps Classic runs a script the portal serves (`backend/app/ci_scripts/azure-classic.{sh,ps1}`).
  It writes `accepted_exemptions` from its own registration response to a file and points the
  scanner at it with `ZEROSTRIKE_ACCEPTED_EXEMPTIONS_FILE`.
- **The layout contract.** The YAML gate counts `^      "Severity": "critical"`: six spaces, a
  field of a `Findings` element. An exempted finding is nested one level deeper
  (`"AcceptedExemptions": [{"Fingerprint", "File", "Kind", "Finding": {...}}]`), so its `Severity`
  is indented eight and the unchanged gate does not count it. `TestReportLayoutContract` in the
  scanner fails if that ever changes. Do not "fix" the test; fix the layout.

## Migration

On startup, `migrate_unreviewed_false_positives` moves every `resolved / false_positive` row that has
no review back to `open` with a **pending** review, keeping the original comment and requester.
Dependency rows marked false positive reopen with no review (that verdict is no longer allowed).
It is idempotent. Expect teams' old false positives to block again until an admin reviews them.

## Verified end to end (2026-10-26)

A synthetic repo (a command-injection high in `src/runner.py`, the minimist 1.2.0 critical) was run
through the portal's own generated GitHub Actions gate, unchanged, and the served Azure Classic
PowerShell script:

| Step | Pipeline |
|---|---|
| No reviews | Blocked (1 critical, 1 high) |
| Member requested FP + accepted risk in the UI | Blocked (pending changes nothing) |
| Admin accepted both in the UI | **Passed**; both still in the report, not counted |
| Admin revoked the accepted risk | Blocked (1 critical) |
| Same snippet copied to `src/other.py` | Blocked: same fingerprint, other file, not exempt |
| Azure Classic (PowerShell, absolute source path) | Exemption applied to `src/runner.py` only |

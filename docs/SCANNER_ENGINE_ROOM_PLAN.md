# Scanner Engine Room: plan

Status: proposal, 2026-10-16. Branch: `feat/scanner-engine-room` (off `master`).

## Problem

A self-scan of the portal produced 25 findings, 15 of them false positives. On a client project, false
positives block pipelines and delay releases. Today, marking a vulnerability `false_positive` keeps that
verdict across scans, but the finding still appears in the scan's findings, counts and report. Nobody sees
which rules are noisy across projects, and nobody can retire or add a rule without a scanner release.

## What already exists (and is reused)

- `Vulnerability` is keyed by `(project_id, repo_scope_key, fingerprint)` and carries
  `resolution_reason = "false_positive"` and `current_rule_id`. A re-scan already leaves that verdict alone
  (`vulnerability_service`, `_SCANNER_OVERRIDABLE_REASONS`).
- `report_ingestion_service.ingest()` is the single place a scanner report becomes portal findings, for
  both cloud and CI scans.
- The scanner already has `--rules <dir>` (replaces the embedded rules), `--allow-file`
  (suppress by rule ID or fingerprint), and a rule `lifecycle` field that includes `retired`.
- The audit log, notifications catalog and admin layout already exist.

## Key design decision: rule pack, not binary rebuild

The request was: an admin adds or retires a rule, the scanner is rebuilt, a new version is published.
Rebuilding the Go binary from the portal needs a Go toolchain with CGO and tree-sitter inside the
production container, write access to the scanner repo, and a build pipeline the portal would have to
babysit. It is slow, fragile, and it couples the two repos the CLAUDE.md says must stay independent.

Instead, the portal publishes a **rule pack version**: a numbered, immutable snapshot of
(retired rule IDs + custom rules). Every scan records which pack version it ran under. Effect is the same
as a new scanner version from the user's point of view (versioned, published, traceable, rollback-able),
with no rebuild. Rules that prove themselves can still be upstreamed into the scanner repo through its
normal release, at which point the portal custom rule is deleted.

## The feature, in three parts

### Part 1. Project-level false-positive suppression (automatic, the fix for release delays)

When a project member resolves a vulnerability as `false_positive`, later scans of that repo do not report
it.

- In `ingest()`, look up the project's `false_positive` fingerprints for that `repo_scope_key` once, and
  mark matching findings `suppressed=True, suppressed_reason="false_positive"` instead of dropping them.
- Suppressed findings are excluded from severity counts, the PDF/HTML report, compliance evidence, and
  pipeline blocking. They are still stored, and the scan page shows "N suppressed as false positive" with a
  toggle to view them. A silently missing finding is an audit hole; a counted one is not.
- Scoped by fingerprint, so the same rule still fires on new code. One project's verdict never affects
  another project.
- Marking a finding false positive already writes an audit row; the reason comment becomes required for
  `false_positive` so the engine room has evidence to show.

### Part 2. Admin "Scan Engine" section (`/admin/scan-engine`, `require_admin`)

**Rules tab.** One row per rule that has ever produced a finding:
rule ID, title, severity, language, total findings, false-positive tags, FP rate, projects affected, state
(active / retired / custom). Sorted by FP tags. Computed by aggregating `Vulnerability` on
`current_rule_id` (counts only, no code from client projects is shown across projects).

- A rule is flagged **Noisy** when it has at least 5 FP tags and an FP rate of at least 40%
  (both workspace settings). Crossing the threshold sends an admin notification, once per rule.
- Row detail: FP tag history (project name, date, who, reason comment), visible only for projects the admin
  can already see.
- Actions: **Retire** (with required reason) and **Restore**. Retiring puts the change in the draft.

**Custom rules tab.** Admin pastes a rule in the scanner's YAML format, plus a short vulnerable sample and
a safe sample. Saving runs the scanner on both samples in a temp directory: the rule must fire on the
vulnerable sample and must not fire on the safe one, and the YAML must pass the scanner's validator.
A rule that fails either check cannot be saved. This is the same positive/negative fixture discipline the
scanner's benchmark uses, and it is what stops a bad custom rule from flooding every client.

**Versions tab.** Pending changes (retires, restores, custom rules added/edited/removed) form a draft.
**Publish** freezes the draft as rule pack version N+1 with a required changelog line, writes an audit row,
and makes it active for the next scan. Each version can be viewed, and **Roll back** re-publishes an older
version's contents as a new version (never rewrites history).

### Part 3. How a published pack takes effect

- **Retired rules:** applied at ingest (`suppressed_reason="rule_retired"`), so it works identically for
  cloud scans and CI scans, with no scanner change.
- **Custom rules:** need one small scanner change: a new `--extra-rules <dir>` flag that loads a directory
  *in addition to* the embedded rules (`--rules` replaces them, which is not what we want). Cloud scans
  write the active pack's custom rules to the scan's temp workdir and pass the flag.
- **CI scans** run the client's downloaded binary, which does not see custom rules in v1. The CI scanner can
  fetch the pack with its existing `--server`/`--token` in a later phase. The scan page says which pack
  version applied and whether custom rules ran.
- `Scan.rule_pack_version` is stamped on every scan and shown on the scan page and report footer.

## Data model (new)

- `Finding`: `suppressed: bool = False`, `suppressed_reason: Literal["false_positive","rule_retired"] | None`.
- `Scan`: `rule_pack_version: int | None`.
- `RuleOverride` (draft + live state): `rule_id`, `state: "retired"|"active"`, `reason`, `updated_by`, `updated_at`.
- `CustomRule`: `rule_id` (prefix `ZS-CUSTOM-`), `yaml`, `vulnerable_sample`, `safe_sample`, `language`,
  `last_validated_at`, `created_by`.
- `RulePackVersion`: `version: int` (unique), `retired_rule_ids: list[str]`, `custom_rules: list[{rule_id, yaml}]`,
  `changelog`, `published_by`, `published_at`. The highest version is active.

## Intelligence, honestly scoped

v1 is self-addressing in the part that matters most: a team's own FP verdicts silence those findings on
every later scan, automatically, without waiting for anyone. Across projects, the portal surfaces which
rules are noisy and tells admins; a human decides to retire, because retiring a rule changes results for
every client.

Not in v1, on purpose:
- **AI-suggested rule fixes.** Feeding FP code samples from several client projects into one LLM prompt
  crosses engagement boundaries. If added later, it must work from one project's samples at a time, run on
  that project's AI provider, and only produce a draft for an admin to review.
- **Automatic retirement.** One project bulk-tagging FPs could silence a rule for everyone.
- **New AI/LLM vulnerability rules** (prompt injection into tool calls, LLM output passed to `eval`/shell/SQL,
  unvalidated model output rendered as HTML, model-chosen file paths). These belong in the scanner repo with
  benchmark fixtures, as a separate workstream after this ships. The custom-rules tab can be used to trial
  them first.

## Task order (each with tests)

1. Scanner repo: `--extra-rules` flag + test (embedded rules still load, extra rule fires). Small.
2. Portal: `Finding.suppressed*`, ingest-time suppression for FP fingerprints, exclusion from counts,
   report and blocking. Tests: FP verdict suppresses on re-scan; same rule on a new fingerprint still
   reported; other project unaffected.
3. Portal: models + `scan_engine_service` (rule stats aggregation, noisy flag, draft, publish, roll back)
   and admin router. Tests incl. non-admin gets 403.
4. Portal: retired-rule suppression at ingest + `rule_pack_version` stamped on scans.
5. Portal: custom rule save with scanner validation on both samples; cloud scan passes `--extra-rules`.
6. Frontend: `/admin/scan-engine` with Rules / Custom rules / Versions tabs; scan page suppressed count and
   toggle; required comment on false-positive resolution.
7. Notification event `scan_engine.rule_noisy` (audience admin).
8. Browser QA pass per CLAUDE.md (both roles, refusal paths, wire checks), then full suites.

## Risks

- **FP abuse to pass a gate.** A member could tag a real issue FP to unblock a release. Mitigations: required
  reason, audit row, suppressed findings stay visible on the scan page, and the engine room shows who tagged
  what. Restricting FP marking to project owners is a one-line change if wanted.
- **Fingerprint drift.** If the scanner changes how it fingerprints, old FP verdicts stop matching and
  findings reappear. That fails safe (noise, not missed issues).
- **Custom rule quality.** The two-sample gate is the minimum; it cannot prove a rule is quiet on real code.
  The Noisy flag catches it afterwards.

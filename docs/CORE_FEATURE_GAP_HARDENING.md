# Core feature gap hardening — compliance, auto-fix, quota, AI analytics

Response to the gap review in `fault.md` / `fault-fixer.md`. Scope was deliberately confined to
features that already exist: no new product areas, no new infrastructure. Fixes are ordered by the
review's own "what I would fix first" sequence.

The one-line summary: the enforcement was already sound almost everywhere — what was missing was
**telling the user what the enforcement did**. Most of this change is honesty plumbing, plus two
places where the pipeline was paying for work it already had.

---

## 1. Compliance trust boundaries

### 1a. SOC 2 and ISO 27001 (ISMS) are the only runnable frameworks

`compliance_catalog.SUPPORTED_FRAMEWORK_KEYS = {"soc2", "iso27001"}`. GDPR, HIPAA, PCI-DSS and
NIST 800-53 stay **defined** — `get_framework()` still resolves them, so an audit that already ran
against one keeps rendering — but `FRAMEWORK_KEYS_ORDERED` (which drives `/compliance/frameworks`
and therefore the wizard) lists only the supported two, and `POST .../compliance-audits` rejects the
rest with a 400 naming what *is* available.

Why a gate rather than deleting 500 lines of catalog: a control catalog is only trustworthy if its
evidence mapping has been reviewed control-by-control, and so far only these two have been. Widening
the set is then a one-line, deliberate edit rather than a side effect of adding catalog data.
`tests/test_compliance_catalog.py` asserts the set explicitly, so widening it fails a test first.

The ISO framework title now reads `ISO/IEC 27001:2022 ISMS (Annex A)` — the review referred to it as
ISMS throughout, and users looking for "ISMS" were not finding it.

### 1b. The score can no longer be read as a compliance percentage

`compliance_score` is `passed / assessed_total` — code-assessable controls only. A framework where
the scanner can speak to 10 of 18 controls could therefore read **100%** while 8 controls were never
assessed at all. The number is unchanged (it is the right number); what changed is that it can no
longer be read as something it is not:

- `FrameworkSummary.coverage_percent` (`assessed_total / controls_total`) is computed by `evaluate`
  and travels with every summary.
- The card is labelled **"Scan-evidence score"**, sub-labelled `N of M code-assessable controls`,
  with a sentence under it: *"Not a compliance percentage. Only X% of this framework's Y controls can
  be assessed from code at all — the other Z need manual review and are excluded from the number
  above."*
- The green rating label "High Alignment" became "No scan-evidenced gaps". A tool that has looked at
  a third of a framework does not get to call the result alignment.

`needs_manual_review` already had a neutral (info, not warning) badge colour and its own filter chip;
that was correct and is unchanged. The disclaimer now states outright that a `Pass` means "the
scanner found nothing matching", not "the control is implemented".

### 1c. Scan coverage is stated, not left to be inferred

The review's sharpest point: *an audit is only as complete as the scans in scope, and nothing said
so.* A project with nine repos and scans on two produced a result that looked exactly as confident as
one with full coverage — the controls simply saw less evidence, and **less evidence reads as `pass`**.

- `project_stats_service.resolve_scope_coverage()` now returns `ScopeCoverage(scan_ids,
  repos_in_scope, repos_with_scans, newest_scan_at)`. `resolve_scope_scan_ids()` is a one-line
  wrapper over it, so every existing caller is unaffected.
- Those counts are persisted on `ComplianceAudit` and returned by the API.
- The result page renders a warning when `repos_with_scans < repos_in_scope` ("N of M repositories in
  scope have no completed scan — controls may read *Pass* simply because nothing was looked at") or
  when the newest scan was already ≥30 days old when the audit ran.

Evidence age is measured against the audit's own `completed_at`, not `Date.now()` — both are server
values, so the sentence stays true (and the render stays pure) however long after the fact it is
read. `scanCoverageGaps()` is exported and unit-tested.

### 1d. AI narrative is unmistakably advisory

The two AI blocks were styled as peers of the deterministic verdict, and "AI Suggested Code Fix" used
the **success** colour with a code icon — which reads as a verdict, not as prose. Now: one block, the
`ai` token, an explicit `Advisory` tag, and the line *"Written after the status was decided. It cannot
change the verdict above."* The disclaimer repeats it at the top of an audit run with narrative.

No backend change was needed here — `_narrate_framework` already never touches `status`, and the
deterministic verdicts are persisted before it runs. This was purely a UI that undersold that fact.

---

## 2. Quota: no silent trims

The backend enforcement was already right (per-scan allowance, usage counted from proposals so it
cannot drift, re-fixes free, one open request per scan, admin-only grants, hard ceiling of 500). The
gap was the last mile: `allocate()` clamps a 10-finding request to the 3 that fit, and the shortfall
went **into the audit log only**. The user saw seven findings without proposals and no explanation —
which reads as "the AI couldn't fix these" rather than "it never looked at them".

- `RemediationJob.quota_skipped` / `.skipped_existing` persist the two reasons a run covered fewer
  findings than were submitted.
- `ScanAutoFixResponse` returns both, so the poll response carries them for the life of the job.
- The trigger toasts the trim at the moment of the click, and a persistent alert under the header
  explains it afterwards, naming the allowance chip as the way to ask for more.

Blocked *actions* already explained themselves: both quota gates raise a 409 whose message names the
limit and tells the user to request headroom, and the frontend surfaces `ApiError.message` verbatim.
That was left alone.

---

## 3. Auto-fix: stop paying twice

Three of the review's five efficiency items were already implemented: triage is the primary gate and
runs with no LLM and no DB; the project overview doc is cached by `(project_id, project_repo_id,
base_commit_sha)`; `_persist_proposal` replaces priors rather than accumulating them.

What was actually being wasted:

**Re-runs redrafted everything.** A finding that already has a proposal costs *nothing* under the
quota — it was charged when first drafted. So a second "fix all" click re-spent a full tool-calling
run per finding to reproduce what was already on screen. `run_job` now drops already-proposed
findings unless the job carries `force=True` (a field that was accepted by the API, logged, and
never read). The work list is resolved **before** the clone, so a job with nothing new to draft
neither clones nor pays for an overview-doc call. The button now reads "Fix remaining findings",
which is what it does.

**The critic ran on dependency bumps.** One extra LLM call per fixable finding, including SCA
findings whose entire patch is one version string taken from the scanner's advisory data. There is no
drafted *logic* there for a reviewer to be skeptical about, and SCA is usually the most numerous
finding class — the pass cost most and bought least exactly there. Skipped under
`remediation_critic_skip_dependency_bumps` (default on, flip to False to critique everything). The
apply gate (baseline scan → patch → re-scan) and human approval both still run, and the proposal
records `critique = {"skipped": "dependency_bump"}` so the UI says why rather than implying a pass.

### Deliberately not done: grouping findings into one prompt

The review suggested grouping by rule/fingerprint so "one class of issue doesn't generate many
separate prompts". Not implemented, on purpose: two findings of the same rule are at different
locations and need different patches, so a shared prompt would produce a patch that applies to one of
them. The mechanism that *does* transfer knowledge across a class already exists —
`fix_pattern_service.recent_accepted(project_id, rule_id)` feeds previously accepted fixes for the
same rule into each bundle as an example.

---

## 4. AI analytics: what moved, not just what is

`by_feature` / `by_model` / `by_project` attribution was already there and already project-isolated.
It was descriptive: it answered "where did the money go", never "why did the bill change".

`get_analytics` now also aggregates the equally-long window immediately before the selected one. The
outer `$match` spans both windows and each facet's own leading `$match` picks the one it reports on,
so the comparison costs **no extra query** — still one round trip.

- `previous_totals` on the response.
- `prev_cost_usd` / `prev_requests` / `cost_delta_usd` / `requests_delta` on every feature row.
- A feature that spent in the previous window and nothing in this one still gets a row, as a negative
  delta — a workflow that *stopped* explains a change as much as one that started. Those zero rows
  are filtered out of the bar chart and the filter dropdown, where they would render as noise.
- A "What changed" card states the movement and names the driving feature: *"Spend is up $11.80
  against the previous 30 days — mostly Auto-fix agent."*

---

## 5. Repeat audit reuse

The evaluator is a pure function of `(frameworks, evidence set)`, and the evidence set is fully
determined by the resolved scan ids. So when frameworks, scope, repo filter, depth and the resolved
scan ids all match a completed audit, re-running reproduces byte-identical verdicts — and pays for
the AI narrative again to do it.

`POST .../compliance-audits` now returns that audit with `reused: true` instead of queueing a new
one; the wizard explains it rather than silently landing the user on a result dated last week.
`refresh: true` in the request body forces a fresh run. Depth is part of the key (a deterministic
audit is not a substitute for one with narrative, or vice versa), the candidate scan is bounded to
the ten newest audits, and a new scan in scope invalidates reuse automatically because the resolved
scan ids change.

---

## 6. Consistency pass

- Frameworks: the catalog endpoint, the wizard, the trigger validation, and the project
  compliance-config tab now all derive from `SUPPORTED_FRAMEWORK_KEYS`. There is no remaining place
  that names a framework the evaluator would refuse.
- The project **Compliance config** tab was a mockup with local state: it listed five frameworks
  (including PCI-DSS as "enabled"), offered enable / auto-audit-on-merge switches wired to nothing,
  and its "Save Changes" reported `success` for a save that never happened. It now renders the real
  catalog with real control counts, its unimplemented policy switches are labelled *Not stored yet*,
  and the save button says plainly that nothing is persisted and points at where audits are actually
  configured. A UI that reports success for a no-op is worse than one that admits the gap.
- `fix-stage-panel` gained the `dependency_bump` skip reason, so "not performed" still explains
  itself rather than falling through to the generic "the patch is unreviewed" copy.

## Verification

`ruff check .` clean; **613 backend tests pass** (`pytest`), including new coverage for: unsupported
framework rejection, coverage + score-ceiling fields, audit reuse and its invalidation, the
dependency-bump critic skip (both directions), re-run dedupe with `force`, quota-trim surfacing, and
per-feature spend deltas. Frontend: `tsc --noEmit` clean, `eslint` 0 errors, **123 vitest tests
pass** including `scanCoverageGaps`.

## Known gaps left open

- **Auto-audit on scan completion** is not implemented (the switch is labelled as such). Audits are
  started by hand.
- **Compliance policy persistence** — nothing on the compliance-config tab is stored. It is now
  honest about that rather than fixed.
- **Per-finding quota preview** on the scan page: the fix button there does not show remaining
  allowance before the click; it relies on the 409's message, which names the limit and the remedy.
  Fetching quota per finding row was not worth the requests.

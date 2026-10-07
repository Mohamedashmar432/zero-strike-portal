# Auto-Fix: optional re-scan gate, honest validation verdict, visible PR outcome

Date: 2026-10-07. Branch: `feat/ado-project-picker`. Planned on Opus 5.5, built on Sonnet 5.5.

## Problem (observed in QA, 2026-10-07)

1. A single-finding "Create PR" shows **Scanner validation: "the finding is resolved on re-scan"**
   next to *New findings introduced: 4* and *Findings before → after: 188 → 188*. The headline in
   `fix-stage-panel.tsx: ValidationStep` keys only on `target_cleared`; the apply gate
   (`ai_remediation_apply_service._rescan_and_judge`) only blocks new findings at
   `blocking_severities`, so 4 low/info findings pass silently. The verdict reads as a clean bill of
   health when it isn't.
2. Admins want the re-scan gate to be **optional**: the AI triage + critic already reviewed the
   patch, and the extra clone + two scanner runs per PR is slow and, as above, noisy.
3. After approval the UI **never shows whether the PR was opened or failed**:
   - polling (`lib/api/polling.ts: APPLYING_STATES`) stops at `validated`, which is a *transient*
     apply state (re-scan passed, push/PR not yet done) — so the page freezes on "Validated" with a
     live Create PR button;
   - a PR-step failure (`_ManualReview`, e.g. the provider refused the PR) ends the job `completed`
     with no `error_message` and no notification;
   - PR audit rows carry no `finding_id`, so the per-finding Activity tab filters them out;
   - `reconcile_stranded_proposals` matches the singular `RemediationJob.proposal_id`, so non-lead
     proposals of a running batch can be flipped to `failed` mid-run, and stranded `validated` /
     `approved` proposals are never reconciled.

## Design

### A. Workspace toggle `rescan_validation_enabled` (default `True`)

- `models/remediation_settings.py: RemediationSettings.rescan_validation_enabled: bool = True`.
  Admin-only, like `blocking_severities` (it governs what may be pushed to a customer repo).
  **No project twin** — a project override could only *re-enable* (tighten); add one when asked.
- Schemas `RemediationSettingsResponse` / `RemediationSettingsUpdateRequest`, the service's update,
  and `frontend/lib/api/auto-fix.ts: RemediationSettings` gain the field. The admin page
  `app/(dashboard)/settings/auto-fix/page.tsx` gets a switch: *"Re-scan before opening a PR"*, help
  text: *"Clones the repo and runs the thinkShield scanner before and after the patch; the PR is
  only opened if the finding clears and no new blocking finding appears. Turning this off opens the
  PR on AI review alone."*
- `_apply` when disabled: skip `baseline_report` and `_rescan_and_judge`. The **scope check is not
  optional** (it costs one `git diff`, and it is what stops a patch touching unexpected files) —
  extract it from `_rescan_and_judge` into `_check_scope(workdir, items) -> str | None` and call it
  on both paths. Stamp each survivor:
  `validation = {"skipped": True, "scope_ok": True, "ran_at": <iso>, "batch_size": n}`.
  Record audit `"AI Fix Validation Skipped"` instead of `"AI Fix Validation Passed"`. Survivors still
  go `validated` → push → PR exactly as today.
- `remediation_brief_service._validation_lines`: when `skipped`, render
  `- Skipped — re-scan disabled in Auto-Fix settings. The PR was opened on AI review alone.`
  (this is what lands in the PR body, so the reviewer knows).

### B. Honest validation verdict

- `_rescan_and_judge` additionally stores
  `new_finding_severities: {severity: count}` for findings in `new_fps` (lower-cased, `"unknown"`
  when missing) and `blocking_severities: sorted(blocking)`.
- `ValidationStep` headline/tone:
  - `skipped` → tone `warn`, *"skipped — re-scan is disabled in Auto-Fix settings"*;
  - not cleared → `bad`, *"the finding was NOT resolved on re-scan"* (unchanged);
  - cleared, 0 new → `ok`, *"the finding is resolved on re-scan"*;
  - cleared, N new → `warn`, *"the finding is resolved, but N new finding(s) appeared below the
    blocking severity"*; list the severity breakdown when present, and label the count
    *"(across the whole PR)"* when `batch_size > 1` (the count is batch-wide by construction).
- Placeholder text before any PR: *"runs when you create the pull request, unless disabled in
  Auto-Fix settings"*.
- Brief: when cleared and new > 0, append the severity breakdown to the *New findings* line.

### C. Visible PR outcome

- **Polling/in-flight**: add `"validated"` to `APPLYING_STATES` and to `fixCapabilities().inFlight`;
  drop `"validated"` from `canCreatePr` and `canRevise` (it is mid-apply). Backend
  `_APPROVABLE_STATES` keeps `validated` for legacy rows.
- **Reconciler** (`ai_remediation_queue_service.reconcile_stranded_proposals`): consider
  `review_state in ("approved", "applying", "validated")` whose `updated_at` is older than 120 s
  (the approve route sets `approved` just before inserting the job), and treat a proposal as covered
  when an active apply job has it in `proposal_ids` **or** `proposal_id`. Uncovered → `failed`
  with the existing message.
- **Job outcome on `_ManualReview`**: also set `job.error_message = str(mr)[:2000]` (status stays
  `completed`: the job ran, the write was refused) and send the same `autofix.apply_failed`
  notification, title *"Auto-fix pull request was not opened"*. One per batch.
- **Audit**: add `"finding_id": proposal.finding_id` to the metadata of *Validation Passed /
  Skipped*, *Branch Pushed*, *PR Opened* and both *Marked Manual Review* records, so the per-finding
  Activity tab shows them.
- **Pull request step** in `FixStagePanel` (after validation), from the proposal alone:
  - `approved|applying|validated` → `idle`, *"creating the pull request…"*;
  - `pr_open` + `pr_url` → `ok`, *"opened"* + link *"#<pr_number>"* to `pr_url`;
  - `manual_review` with reason → `bad`, *"not opened"* + the reason;
  - `failed` with reason → `bad`, *"failed"* + the reason;
  - otherwise not rendered.
- **Transition toast** in `CreatePrButton` (`fix-actions.tsx`): remember the previous
  `review_state` in a ref; when it moves from in-flight to `pr_open` → `toast.success("Pull request
  opened", {action: View PR})`; to `manual_review`/`failed` → `toast.error("Pull request was not
  opened", {description: reason})`.
- **Activity refresh**: after approve (single and batch) also invalidate the activity query key
  `["ai","autofix","activity",scanId]`.

## Tests

Backend (`tests/test_remediation_apply.py`, `test_remediation_batch_apply.py`,
`test_remediation_settings.py`, `test_remediation_brief.py`):
- rescan disabled → `run_scanner` never called, PR opened, `validation.skipped is True`, audit
  "AI Fix Validation Skipped";
- rescan disabled + patch touching an unexpected file → still manual_review (scope enforced);
- `new_finding_severities` populated on a low-severity new finding that does not block;
- `_ManualReview` at PR step → `job.error_message` set, notification sent;
- reconciler: a non-lead batch proposal `applying` under a running job is NOT flipped; a stranded
  `validated` older than 120 s IS flipped; a fresh `approved` (< 120 s) is not;
- settings round-trip of `rescan_validation_enabled`; brief renders the skipped line.

Frontend (vitest): `fix-stage-panel.test.tsx` (warn headline, skipped, PR step states),
`polling.test.ts` (validated keeps polling), `fix-actions.test.tsx` (validated is in flight, no
Create PR button).

## Browser pass

Admin: toggle the switch off/on on Settings → Auto-Fix, confirm the PUT body and persisted value.
Create PR on one finding with re-scan **off** → Pull request step goes "creating…" → "opened #N"
without a reload, toast fires, Checks tab shows "skipped", Activity tab shows PR Opened. Repeat
with re-scan **on**. Member role: settings page refuses. Finish with console + network clean.

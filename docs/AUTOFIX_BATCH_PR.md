# Auto-Fix: batch apply, one PR

Status: implemented on `feature/autofix-batch-pr`.
Supersedes nothing; extends `docs/AI_AUTOFIX_DESIGN.md`.

## The flaw

The remediation pipeline is finding-scoped end to end: one `AIFixProposal` per finding,
one `POST /fix-proposals/{id}/approve` per proposal, one `RemediationJob(kind="apply")`
per proposal, one branch and one PR per job. A scan with 40 approvable findings produces
40 branches and 40 PRs.

That is not just review overhead. Each apply job independently clones the repo and runs
the scanner **twice** (baseline + post-patch), so 40 fixes cost 40 clones and 80 scanner
runs against the same tree.

## What does *not* change

Per-finding granularity is the product's traceability story and it stays exactly as it is:

- one proposal per finding, with its own diff, triage, critique, conversation, comments
- independent review state, dismiss, revise, and Ask-AI per proposal
- the existing single-proposal approve route, unchanged, for the one-off case

The change separates **proposal granularity from PR granularity**. Nothing else.

## Design

### No new collection

`RemediationJob` already carries `finding_ids: list[str]` for the propose kind. The apply
kind gains the symmetric `proposal_ids: list[str]`. **The job *is* the batch entity** — it
already has status, stage, trace_id, approver, retry policy, and a dedup `scope_key`. A
separate `remediation_batch` document would duplicate all of that to hold three extra
fields.

`proposal_id` (singular) stays on the model so rows written before this change still run;
the worker reads `job.proposal_ids or [job.proposal_id]`.

The batch's PR identity lives where it already lives — `branch_name`, `commit_sha`,
`pr_url`, `pr_number`, `pr_provider` on each included proposal, all set to the same
values. "Which fixes are in this PR" is a group-by on `pr_url`, not a new field.

### Grouping rules are mostly already satisfied

The doc-suggested compatibility signals (same repository, same branch, same scan) are
**structurally guaranteed** by scoping a batch to one `scan_id`: a scan has exactly one
`repo_url`, one `project_repo_id`, one base branch. Writing a grouping engine to
re-derive that would be inventing a constraint the data model already enforces.

The one signal that is *not* free is patch conflict, and it is not predictable from
metadata — two patches in the same file may or may not both apply. So the pipeline does
not predict; it **applies and observes**, and degrades per-proposal:

- a patch whose `original_code` no longer matches uniquely is skipped, not fatal
- a patch that fails the re-scan gate is dropped from the batch, not fatal
- the remaining patches still ship as one PR

That is Option C (hybrid) from the analysis, implemented as *outcome-driven* splitting
rather than *prediction-driven* grouping — strictly more accurate and much less code.

### Apply pipeline, batched

`ai_remediation_apply_service._apply` takes a list instead of one proposal:

1. Resolve repo + write credential **once** (all proposals share `scan_id`).
2. Clone once. Baseline scanner run once.
3. Apply each patch in turn into the same worktree. A per-patch failure (file missing,
   source drifted, non-unique match, path escape, target fingerprint absent from the
   baseline) marks *that* proposal `manual_review` and continues.
4. Scope check: `git diff --name-only` must equal exactly the set of file paths of the
   patches that applied.
5. Post-patch scanner run once. Per proposal, `target_cleared = fingerprint ∉ post`. New
   findings at a blocking severity are attributed to the patch that touched their file.
6. If anything failed the gate — a target that did not clear, or a patch blamed for a new
   blocking finding — **reset the worktree, re-apply only the survivors, and re-scan once
   more.** Bounded at three scanner runs total, worst case. If the survivor set is still
   dirty, or a new blocking finding landed in a file no patch touched (unattributable),
   the whole batch goes to `manual_review` with that reason.
7. One branch, one commit staging every surviving file, one push, one PR.

Cost for N fixes: 1 clone + 2 scanner runs (3 if a patch misbehaves), versus N clones and
2N scanner runs today.

Whole-batch `_ManualReview` conditions are unchanged in kind (no connected repo, no write
credential, unsupported provider, push denied, PR call failed) and now resolve *every*
proposal in the batch to `manual_review` with the same reason — the same outcome the
single-proposal path already produced, N times.

### Traceability inside the PR

The PR body keeps `remediation_brief_service.render_proposal_section` per included fix —
the same renderer the downloadable brief uses — under a summary table listing every
finding considered:

| finding | rule | severity | file | status |

with `included` / `skipped — <reason>` per row, so a reviewer can see what was left out
without leaving the PR. The commit message lists each rule fixed under the existing
`zero-strike/security fix:` convention.

Audit rows stay per proposal (`AI Fix Validation Passed`, `AI Fix Branch Pushed`,
`AI Fix PR Opened`) so the existing audit-log surfaces and per-finding history keep
working, with the batch's job id in the metadata.

### API

- `POST /fix-proposals/{id}/approve` — unchanged, wire-compatible. Now a batch of one.
- `POST /scans/{scan_id}/auto-fix/approve-batch` — `{proposal_ids, branch_name?}`.
  Owner/admin only, same as single approve. Rejects proposals from another scan,
  proposals with no applicable patch, and proposals already PR'd or already in an active
  apply job; returns the accepted set so the UI can say what it skipped.

Both routes funnel through one `_enqueue_apply(proposals, user, branch_name)` so the
approval semantics cannot drift between them.

### UI

The proposal list gains a checkbox per approvable row plus "select all shown"; a batch
bar appears when the selection is non-empty:

> **7 fixes selected** · 6 files · `Create one PR`

The confirm dialog lists the files and warns that any fix failing validation is dropped
from the PR rather than blocking it. The per-finding detail pane and its single
`Create PR` button are untouched — the drill-down stays the drill-down.

A batch is partial by design, so both halves of the trim are named on screen rather than
only in the PR body. The approve toast reports **every** skip reason with a count, not the
first one (a reviewer who ticked twelve boxes and got nine queued needs all three reasons),
and `failure_reason` is on `FixProposalOut` so a proposal the apply job left `failed` says
why on its card — without it the card reads "failed" and the batch outcome is unreadable.

## Deliberately not built

- **A `remediation_batch` collection.** The job already is one. Add it when a batch needs
  to outlive its job or span scans.
- **Predictive grouping by file/module/rule/risk class.** Scan scope already fixes
  repo/branch; conflict is discovered more accurately than it is predicted.
- **Cross-scan or cross-repo batching.** One PR cannot span two repositories anyway.
- **Auto-batching every proposal on propose.** Batching at approve time keeps the human
  in control of what ships together, which is the whole point of the review step.

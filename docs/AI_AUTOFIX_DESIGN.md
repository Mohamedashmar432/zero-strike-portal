# AI Auto-Fix (AI Remediation) — Design

Source of truth for the AI Auto-Fix feature. Supersedes the propose-only scoping sketched in
`ARCHITECTURE_REVIEW_AND_AI_ROADMAP.md` §B: Auto-Fix now goes all the way to **opening a PR**, but
only ever after an explicit human approval — the LLM never writes to a repo.

## What it does

For a scanner `Finding`, an AI agent proposes a concrete code patch (`AIFixProposal`). A human reviews
the diff and, if they approve, the portal clones the repo, re-validates the patch with the scanner,
pushes a branch, and opens a pull request. Nothing is auto-committed and nothing is auto-merged.

## Two-phase, job-based

Both phases run as `RemediationJob`s on the generic Mongo-backed queue (`core/job_queue.py`), a third
peer of the cloud-scan and AI-analysis queues (`ai_remediation_queue_service.poll_loop()` in the
`main.py` lifespan). No new infra (no Redis/Celery) — Mongo + asyncio, matching the rest of the stack.

```
[Propose]  kind="propose"
  trigger (POST /scans/{id}/auto-fix or /findings/{id}/auto-fix)
    -> ai_remediation_service.run_job
    -> best-effort shallow clone (degrades to stored-excerpt-only if unavailable)
    -> per finding:
       1. remediation_triage.triage           deterministic, NO LLM — skip the hopeless
       2. bounded + secret-redacted issue_bundle (+ prior accepted fixes for this rule)
          -> ai_remediation_agent.run_agent   read-only tool loop on litellm function-calling
       3. remediation_critic.critique         ONE LLM call reviewing the draft
          -> "revise" -> one redraft through the agent's trusted revision_note channel
       4. AIFixProposal(status="proposed", triage=…, critique=…)

[Apply]  kind="apply"   (only after human approval)
  approve (POST /fix-proposals/{id}/approve, require_owner_or_admin)
    -> ai_remediation_apply_service.run_job
    -> clone-on-approval -> baseline scan -> apply patch -> scope-allowlist -> post-patch scan
    -> git branch/commit/push -> open PR
    -> AIFixProposal(review_state="pr_open", pr_url, ...)
  Async; the UI polls.
```

## Design invariants (non-negotiable)

- **The agent is read-only.** During proposal generation the LLM gets only READ tools
  (`list_branches`, `list_files`, `read_file`, `read_excerpt`, `compute_diff`) plus a terminal
  `submit_fix_proposal` tool. It never gets `create_branch`/`commit_patch`/`open_pr`, and it never sees
  a repo token.
- **Nothing auto-commits.** Branch/commit/push/PR happen only in the deterministic apply step, gated on
  an explicit human approval — never inside the LLM loop.
- **Validate before any remote mutation.** `clone → baseline scan → apply patch → scope-allowlist →
  post-patch scan` all run on the local worktree; a failing gate never creates a remote branch. Any
  unsafe condition resolves to `review_state="manual_review"` with a specific reason — never a force.
- **Repo content is untrusted.** It enters the prompt only as delimited tool-result data, never merged
  into the system prompt, and secrets are redacted before injection.

## LLM approach

A controlled tool-calling loop on **litellm's native function-calling** (`llm_client.get_tool_completion`),
not a second agent framework — this keeps the existing provider routing, encrypted keys, and per-call
usage accounting. Requires a tool-capable provider
(`settings.remediation_tool_capable_providers` + `litellm.supports_function_calling`); the trigger returns
409 otherwise. Local LM Studio / custom providers are excluded (unreliable tool-calling) — the accepted
tradeoff for the agent path.

The loop enforces a step budget, a token budget, a per-finding wall-clock (`asyncio.wait_for`), and a
repeated-invalid-output fail-fast. On any budget exhaustion it returns a `can_fix=False` proposal so one
bad finding never fails the whole job. The confidence gate (`can_fix=True` and
`confidence_score >= remediation_confidence_threshold`, default 80) is applied at surfacing/read time, not
by discarding — a `can_fix=False` proposal is itself the audit record of "not safely auto-fixable".

## Propose-phase gates (before and after the draft)

Both exist because the deterministic apply-phase gate below only runs **after a human approves** — so
without them, a hopeless finding costs a full agent run and a plausible-but-wrong diff costs a
reviewer's attention.

### 1. Deterministic triage (`remediation_triage.py`) — no LLM, no DB

Pure function over a `Finding`. Answers only "could an agent run here *possibly* produce a patch the
apply step would accept?" Every rule encodes mechanical impossibility, never a judgement about
difficulty — deciding a fix is too hard remains the agent's job (`can_fix=False`, honestly).

Ineligible ⇒ an `AIFixProposal(can_fix=False, review_state="manual_review")` is written directly with
the reason, and **no LLM call is made**:

- no `location.file` — nothing to scope a patch to
- vendored/build path (reuses `remediation_tools._SKIP_DIRS`) — patching it is overwritten on the next
  install/build, or belongs upstream
- generated/minified artifact or lockfile — change the source or manifest instead
- binary extension — not patchable as text
- `kind == "sca"` with no scanner-reported `fixed_version` — no safe version to bump to
- **`kind == "secret"`** — proven in `tests/test_remediation_triage.py`: every path that shows the agent
  the offending line redacts the literal first (`_redacted_snippet` blanks the whole line;
  `dispatch`'s `read_file` replaces the value), so any `original_code` spanning it is absent from the
  real file and `_apply_patch` rejects it as "source changed". The reviewer gets a rotate-the-credential
  instruction instead of an unexplained apply failure.

### 2. Critique pass (`remediation_critic.py`) — one LLM call

Reviews the drafted patch on five axes (resolves the finding / introduces risk / breaks callers / style
consistent / simpler fix available) and returns `pass | revise | reject`. Uses
`llm_client.get_completion` (JSON out), so unlike the agent it works on **every** configured provider,
not just tool-capable ones.

- `reject` → `can_fix=False`, `manual_review` with the critic's reasoning. Never approvable.
- `revise` → **one** redraft, fed back through the agent's existing *trusted* `revision_note` channel
  (the same one a human reviewer uses — no new plumbing). Still `revise` after the budget ⇒ treated as
  `reject`, because the named defect is still there.
- `pass` → kept, with `confidence_score = min(agent, critic)`. The critic can only ever **lower**
  confidence, never inflate it.
- Any failure ⇒ `critique = {"skipped": reason}` and the draft stands unchanged. A critic outage must
  never become a fix outage. The UI renders "not reviewed", never an implied pass.

### SCA context in the issue bundle

`_issue_bundle` includes a `dependency_update` block (package, current + recommended version,
manifest, and an explicit bump instruction) for SCA findings. This is load-bearing: it was previously
computed only for the UI's version picker and never handed to the agent, so on every dependency
finding the model replied *"no fixed version was specified by the scanner"* and returned
`can_fix=false` — SCA auto-fix could not succeed at all. Found by an end-to-end run, not by the unit
tests, which mocked the agent. Scanner data only; no registry calls.

Path hygiene: the scanner is invoked with an absolute temp clone dir and echoes that prefix back, so
`report_ingestion_service` normalizes it out of `location.file`, `dependency.manifest`,
`config.config_file`, **and** free text (`message`/`rationale`/`remediation` — some rules interpolate
the path into the sentence). `_repo_relative_manifest` re-checks at read time so findings ingested
before those fixes don't leak the workdir into a prompt, the UI, or a brief without needing a rescan.

## Fix memory (`fix_pattern.py`, `fix_pattern_service.py`)

Per-project memory of how a rule was actually fixed, so the next occurrence doesn't start from zero.
Keyed on `(project_id, rule_id)` — a fingerprint identifies one *occurrence* (that's what
`AIFindingInsight` caches on), whereas the reusable knowledge is "how do we fix this *class* here".

- **Written** at the two terminal human decisions: PR opened (`outcome="pr_open"`) and dismissed
  (`outcome="dismissed"`).
- **Read** into the issue bundle as `previously_accepted_fixes_for_this_rule` — **only `pr_open` rows**,
  which cleared the scanner re-scan gate *and* a human approval. A dismissed patch is one a human
  rejected; showing it as an example would teach exactly the wrong thing. Dismissals are kept for
  analytics only.
- Entering as untrusted context, redaction-capped and length-capped, like any other repo content.

## Validation gate (apply phase)

1. **Scope allowlist** — the patch is applied by exact-match replacement of a unique `original_code`
   substring in the single `file_path`; `git diff --name-only` must equal `{file_path}`; reject
   `..`/absolute/symlink-escape.
2. **Scanner re-run (fresh baseline)** — run the ZeroStrike scanner on the clean clone (baseline
   fingerprints), apply the patch, run again. The target finding's fingerprint must disappear AND
   `post \ baseline` must contain no new finding of severity ≥ medium.
3. **No repo test-suite / lint execution.** Running a third-party repo's own `npm test`/`pytest` is
   arbitrary code execution on the portal host; the platform deliberately never executes target code
   (the scanner is static). An ephemeral, network-less, resource-capped sandbox is the documented
   prerequisite before this can be enabled.

## Git write

Local `git` CLI for branch/commit/push (reusing the token-injected clone from `git_workspace`), provider
REST for the PR only:
- **GitHub** — `POST /repos/{owner}/{repo}/pulls`. The `repo` OAuth scope / a classic `repo` PAT already
  grants push + PR; no scope change needed.
- **Azure DevOps** — resolve the repo GUID, then `POST .../_apis/git/repositories/{id}/pullrequests`. The
  OAuth scope widens from `vso.code` (read-only) to **`vso.code_write`**; existing Azure connections must
  **re-consent** (an OAuth grant's scope is fixed at consent and preserved across refresh). A read-only
  token → `manual_review`.

The auth-channel split already encoded on `Scan.repo_token_auth_scheme` is reused: git-over-HTTPS uses
Basic for GitHub/Azure PATs and GitHub OAuth tokens, Bearer for Azure AAD tokens; the GitHub REST PR call
uses Bearer.

## Data

- **`RemediationJob`** (`ai_remediation_jobs`) — claimable queue doc: `kind`, `project_id`, `scan_id`,
  `finding_ids[]` / `proposal_id`, `target_ref`, `scope_key`, `status`, `stage`, `retry_count`,
  `max_attempts` (propose=2, apply=1 — writes never auto-retry), `trace_id`, `progress_*`, `provider`,
  `model_name`, `created_by`, `approver_user_id`, `credential_source`, `connection_id`, timestamps.
  `stage` is a **coarse, advisory** sub-phase of `status="running"` (propose:
  `cloning → triage → proposing → critiquing → finalizing`; apply:
  `cloning → baseline_scan → patching → rescan → pushing → opening_pr`). `core/job_queue.py` claims and
  reaps on `status`, which is unchanged — never gate logic on `stage`. It is job-level on purpose: a
  propose job spans up to `max_findings_per_job` findings, so a per-finding stage would be ambiguous;
  per-finding progress is `progress_completed`/`progress_total` and per-finding *artifacts* live on the
  proposal.
- **`FixPattern`** (`ai_fix_patterns`) — see Fix memory above.
- **`AIFixProposal`** (`ai_fix_proposals`, extended) — the durable reviewable record:
  `review_state` (`proposed|approved|applying|validated|pr_open|manual_review|dismissed|failed`),
  `file_path`, `remediation_job_id`, `trace_id`, `risk_notes`, `base_branch`, `base_commit_sha`,
  `branch_name`, `commit_sha`, `pr_url`, `pr_number`, `pr_provider`, `validation`, `approved_by`,
  `approved_at`, `manual_review_reason`, `failure_reason` — on top of the original CLI-parity fields
  (`can_fix`, `confidence_score`, `original_code`, `patched_code`, `explanation`, `patch_scope`).
  Plus three **per-stage artifact** dicts, one per pipeline stage that can independently stop a fix, so
  a reviewer can see *which* stage stopped it and why without re-running anything: `triage`
  (deterministic, pre-LLM), `critique` (post-draft AI review), `validation` (scanner re-scan). All three
  are surfaced on `FixProposalOut` and rendered by the UI's **Checks** tab.

## Generated Markdown (`remediation_brief_service.py`)

Mongo is the source of truth; Markdown is a *generated artifact* only. `render_scan_brief(scan_id)` is a
pure function over the stored documents — no LLM, no repo read, no persistence — so identical documents
produce identical bytes and two renders can be diffed directly. The only wall-clock value is the single
generated-at header line (asserted in `tests/test_remediation_brief.py`). Served as an attachment from
`GET /scans/{id}/auto-fix/brief`; not cached, because caching a pure Mongo read is premature.

`render_proposal_section()` has two callers: the brief (with the diff) and
`ai_remediation_apply_service._open_pr` for the PR description (without — the PR *is* the diff, but the
finding detail and re-scan evidence still belong there). One definition of "how we describe a fix".

Do not confuse this with `remediation_project_doc_service`, which asks an LLM to summarize a clone —
that output is non-deterministic and repo-derived, the opposite of this.

## Security controls (per the 10 concerns in the source dev note)

- **Prompt injection** — repo text only as delimited tool-result/untrusted-bundle data; static hardened
  system prompt; typed tool-calling only; repo/branch/paths pinned in a non-LLM-visible `ToolContext`.
- **Secret exposure** — `secret_redaction.redact` on every file-bearing tool result;
  `.git/`/`.env*`/known-secret-file denial; audit persists metadata only, never raw prompts/tokens.
- **Over-broad permissions** — agent read-only; writes gated to the human-approved apply step;
  `allowed_paths` derived from the target findings' files.
- **Unsafe changes** — `can_fix` + confidence gate + `patch_scope`, scope-allowlist, double scanner
  re-scan, mandatory human approval.
- **Cross-tenant** — every job pinned to `project_id`; `require_member` (trigger) /
  `require_owner_or_admin` (approve); a fresh clone + fresh message list per job.
- **Provider** — admin-only config, encrypted keys, tool-capable allowlist, per-project metering via
  `AIUsageEvent`.
- **Tool abuse** — JSON-schema tools, Pydantic-validated + server scope-checked; no shell/network/
  arbitrary-path tools.
- **Unauthorized PR** — membership + owner/admin gate; token + reachability re-validated at apply; every
  write audited.
- **Runaway cost** — step/token/wall-clock budgets, `max_findings_per_job`, queue concurrency, fail-fast,
  metering.
- **Auditability** — per-job `trace_id` on every proposal + audit event; capped step-metadata log; PR
  linked to scan + job id.

## Config knobs (`core/config.py`, `remediation_*`)

`max_concurrent_remediation_jobs`, `remediation_job_timeout_seconds`, `remediation_queue_stuck_multiplier`,
`remediation_agent_max_steps`, `remediation_agent_token_budget`, `remediation_agent_wall_clock_seconds`,
`remediation_max_invalid_steps`, `remediation_max_findings_per_job`, `remediation_confidence_threshold`,
`remediation_max_file_bytes`, `remediation_max_excerpt_lines`, `remediation_llm_request_timeout_seconds`,
`remediation_max_output_tokens`, `remediation_tool_capable_providers`,
`remediation_critic_enabled` (kill switch — off leaves the pipeline exactly as it was pre-critic),
`remediation_critic_max_redrafts` (1 — bounds worst-case per-finding cost at two agent runs),
`remediation_critic_max_output_tokens`.

## Deliberately not built

Recorded so these aren't re-litigated. The `ai-auto-fix-re-gap.md` note proposed a seven-agent
decomposition (triage → context → planner → generator → validator → test-runner → finalizer); what
shipped instead is the two gates above, because:

- **The "validator agent" already exists and is stronger than an LLM.** The apply gate is a real scanner
  re-run on a fresh clone, not a model's opinion.
- **Context-gathering and planning already happen inside the agent loop** — it has `list_files` /
  `read_file` / `read_excerpt` / `compute_diff` against a real clone. Separate agents would re-derive it.
- **Test synthesizer / test runner** — refused; see "No repo test-suite / lint execution" above. Needs a
  sandbox first.
- **Per-stage model routing** — the motivation was a cheap model for triage, but triage is now zero-LLM,
  and a *weaker* critic than the drafter is worse than no critic. `AIProviderConfig` is a single-active
  singleton; going multi-role is schema + admin UI for no quality gain here.
- **Seven agents** would cost ~6× tokens and latency per finding at `max_concurrent_remediation_jobs=1`.

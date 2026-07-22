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
    -> per finding: bounded + secret-redacted issue_bundle
       -> ai_remediation_agent.run_agent  (read-only tool loop on litellm function-calling)
       -> AIFixProposal(status="proposed")
  NO clone. Runs on stored Finding context (evidence.snippet, location, taint_context, remediation text).

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
  `finding_ids[]` / `proposal_id`, `target_ref`, `scope_key`, `status`, `retry_count`, `max_attempts`
  (propose=2, apply=1 — writes never auto-retry), `trace_id`, `progress_*`, `provider`, `model_name`,
  `created_by`, `approver_user_id`, `credential_source`, `connection_id`, timestamps.
- **`AIFixProposal`** (`ai_fix_proposals`, extended) — the durable reviewable record:
  `review_state` (`proposed|approved|applying|validated|pr_open|manual_review|dismissed|failed`),
  `file_path`, `remediation_job_id`, `trace_id`, `risk_notes`, `base_branch`, `base_commit_sha`,
  `branch_name`, `commit_sha`, `pr_url`, `pr_number`, `pr_provider`, `validation`, `approved_by`,
  `approved_at`, `manual_review_reason`, `failure_reason` — on top of the original CLI-parity fields
  (`can_fix`, `confidence_score`, `original_code`, `patched_code`, `explanation`, `patch_scope`).

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
`remediation_max_output_tokens`, `remediation_tool_capable_providers`.

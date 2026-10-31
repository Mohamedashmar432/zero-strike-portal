# AI Agent Assessment and Strands Agents SDK Evaluation

Date: October 31, 2026. Scope: every LLM-backed feature in `backend/app` (AI analysis, Auto-Fix agent,
critic, compliance narrator, fix Q&A), compared against the Strands Agents SDK (`strands-agents` 1.63.0,
released October 30, 2026), with a path to an automated pentest agent.

This assessment is based on the code only. No production usage data was pulled, so every efficiency
figure below is an estimate from the code's structure and published provider pricing, not a measurement.
Recommendation 1 exists to replace these estimates with real numbers.

## 1. Verdict

Do not migrate the existing features to Strands now. Their main problems are not missing framework
features. They are design choices that a framework would carry over: analysis verdicts are made without
the code, nothing is cached, nothing is measured, and Auto-Fix runs findings strictly one after another.
Fixing those inside the current litellm stack is cheaper and lower-risk than rewriting it, and it produces
the baseline any later migration needs to be judged against.

Adopt Strands for new agentic work, starting with the pentest and exploit-validation agent. That work
needs what we have not built and should not hand-roll: a general tool loop, multi-agent orchestration,
human-in-the-loop interrupts, a pluggable sandbox, and OpenTelemetry traces. Once that agent proves the
SDK runs well on Azure, move Auto-Fix behind the same `Agent` abstraction. Keep the single-shot
features (analysis, critic, narrator) on `llm_client`, because a framework gives them nothing.

## 2. How the current agents work

All features go through `services/llm_client.py`: litellm `acompletion`, three retries with tenacity
backoff, failover across provider configs on transient errors only, the budget hard stop before every
call, and one `AIUsageEvent` per call. This shared foundation is sound. BYOK isolation, cost-unknown
handling and the closed error vocabulary are better than what most frameworks ship by default.

| Feature | Pattern | LLM calls | Concurrency |
|---|---|---|---|
| AI analysis (`ai_analysis_service.py`) | Batched single-shot JSON, 6 to 8 rule-group representatives per call, plus one synthesis call | About groups / 7 + 1 per scan | 3 chunks per job, 3 jobs |
| Auto-Fix propose (`ai_remediation_agent.py`, `remediation_tools.py`) | Hand-rolled tool loop with 5 read-only tools and a terminal `submit_fix_proposal` | 2 to 28 per finding (up to 12 turns, a forced submit, the critic, and a full redraft on "revise") | Findings strictly sequential, 1 job at a time |
| Critic (`remediation_critic.py`) | Single-shot JSON, can only lower confidence or reject | 1 to 2 per finding | Inline |
| Compliance narrator (`compliance_audit_service.py`) | Single-shot JSON per framework, cannot move verdicts | 1 per framework | Inline |
| Apply and re-scan (`ai_remediation_apply_service.py`) | Deterministic, no LLM | 0 | - |

The safety design is strong. The Auto-Fix agent only reads a temp clone. Path containment and symlink
rejection are enforced twice, at read time and at apply time. Patches are written only after a human
approves them, and the scope check rejects any file the proposal did not name. Compliance verdicts stay
deterministic. These properties must survive any migration.

## 3. Efficiency and quality findings, ranked

1. **False-positive verdicts are made without the code, then copied across the whole group.**
   `_finding_payload` sends only rule, message and location, with no snippet (`ai_analysis_service.py:166-183`).
   One representative's `is_false_positive` is then applied to every finding with the same `rule_id`
   (`ai_analysis_service.py:312-321`). A test-fixture false positive can therefore suppress a real
   production instance of the same rule. This is the most serious quality issue, and it has nothing to do
   with which framework we use.
2. **BYOK defect in analysis.** `get_active_config()` is called without `project_id` at
   `ai_analysis_service.py:348` and `:443`. As a result, batch size and provider attribution come from the
   portal config. On a BYOK-only setup, synthesis fails after the enrichment tokens are already spent.
3. **No prompt caching anywhere, and agent history grows without bound.** Every Auto-Fix turn re-sends the
   full system prompt, the tool schemas and the whole history. One `read_file` of up to 200k characters
   uses most of the 60k-token budget and forces an early submit. Input cost grows roughly with the square
   of the turn count.
4. **`compute_diff` diffs against the finding excerpt, not the real file** (`remediation_tools.py:259,333-337`),
   so the agent's self-check is misleading in clone mode.
5. **A "revise" verdict restarts the agent from scratch** (`ai_remediation_service.py:325,344`) instead of
   continuing the conversation, so every exploration turn is paid for twice.
6. **Critic output is laundered into a trusted channel.** The critic reads untrusted repo code, and its
   `issues` are re-injected as a "TRUSTED reviewer revision request" (`ai_remediation_agent.py:197-207`).
   A crafted comment in a repo can therefore steer the fixer through the critic.
7. **Timeouts and retries conflict.** The 180 s per-finding wall clock is shorter than three 90 s retries,
   so failover rarely gets a chance to run. With findings sequential, a 20-finding job takes tens of minutes.
8. **One model for every task.** The critic, repo overview, synthesis and narrator could run on a cheap
   model. Only the fixer needs a strong one.
9. **No evals and no quality metrics.** `FixPattern.outcome`, critic verdicts and re-scan results are
   stored, but nothing computes acceptance rate, re-scan pass rate or false-positive precision.
   `AIUsageEvent` has no `job_id`, `finding_id` or step index, so per-finding agent cost cannot be
   reconstructed.
10. **Smaller issues.**
    - A truncated response triggers a retry that will truncate again.
    - Unpriced (local) calls count as $0 toward USD budgets.
    - The analysis and narrator prompts lack untrusted-data framing.
    - Raw provider error text reaches the user-visible `ai_note`.

## 4. Strands Agents SDK at a glance

Strands is AWS's open-source agent SDK: Apache-2.0, 1.0 since July 2025, 88 releases, currently shipping
one or two releases a week. Its loop is model-driven: tools are `@tool`-decorated Python functions, and
the agent calls the model, runs the requested tools, and repeats until the model stops.

| Capability | Strands | thinkShield today |
|---|---|---|
| Tool loop | Built in, concurrent tool execution | Hand-rolled, sequential, about 250 lines |
| Providers | OpenAI, Anthropic, LiteLLM, Ollama, OpenAI-compatible (LM Studio), Bedrock and others. **No first-party Azure OpenAI**; Azure goes through LiteLLM, which has an open structured-output bug (#1076) | litellm, all providers incl. Azure |
| Structured output | Pydantic models via tool calling | `json_object` mode or prompt plus extraction |
| Context management | Sliding window, summarizing, proactive compression | None |
| Prompt caching | Automatic cache points, documented mainly for Bedrock | None |
| Human in the loop | First-class interrupts from hooks, resumable | Approval happens outside the agent |
| Guardrail hooks | `BeforeToolCallEvent` can cancel any call | Dispatch-level validation |
| Multi-agent | Agents-as-tools, Swarm, Graph, Workflow, A2A | None |
| MCP client | Built in | We serve MCP; we don't consume it |
| Observability | OpenTelemetry GenAI traces, per-cycle token metrics | `AIUsageEvent` rows, no traces |
| Cost | **Not computed**; tokens only | `pricing_service` with `cost_known` |
| Sandbox | Pluggable: `DockerSandbox`, SSH, custom. No default; without one, tools run on the host | Temp clone, read-only tools |
| Evals | `strands-agents-evals`: LLM-judge, trajectory and tool-selection evaluators | None |

### What migrating Auto-Fix would gain

The gains come from features our loop lacks, not from Strands being faster:

- Prompt caching on providers that support it.
- Context compression, so a large file read no longer blows the budget.
- Concurrent tool calls.
- Continuing the conversation on a "revise" verdict instead of restarting it.
- Traces.

**Estimate.** Prefix caching and continuation should cut 40 to 70 percent of Auto-Fix input cost on
Anthropic and OpenAI, and latency should fall meaningfully. Every one of those items can also be
implemented in `llm_client` and the existing loop in a few days. The real argument for Strands is not
efficiency. It is that Strands is a better foundation for agents we have not built yet.

### Pros

- A maintained loop, hooks, interrupts and multi-agent primitives, which a pentest agent needs.
- OpenTelemetry tracing and an evals SDK, which close our largest observability gap.
- A pluggable sandbox interface.
- Provider breadth compatible with BYOK.

### Cons and risks

- **Azure is second-class**, and Azure is our hosting platform.
- **`boto3` is a hard dependency** even when AWS is never called.
- **Bedrock is the default model** when none is set.
- **Caching and evals examples assume Bedrock.**
- **API churn is fast**: tools are being deprecated into the core and the repo was restructured. Strict
  pinning is required.
- **Published advisories.** Three are against the SDK:
  - GHSA-3w55-933p-8pv5: symlink privilege escalation in `FileSessionManager`, 7.1.
  - GHSA-763v-5pjm-fx36: world-readable session files, 5.5.
  - CVE-2026-115419: A2A session data exposure, 8.1.

  The first two mean we must not use the file session manager in a multi-tenant container. The third
  means we must not run the A2A server.
- **`strands-agents-tools` is beta** and self-described as experimental. We would write our own tools
  rather than install it.
- **No cost accounting.** Our `AIUsageEvent` writes, budget hard stop and BYOK failover policy would move
  into a model-call hook. That is doable, but it is a rewrite of the most audited part of the AI layer.

## 5. Automated pentest agent

### Positioning

Do not build a general autonomous pentester first. Build **exploit validation of our own SAST findings**:
the scanner already tells us where a SQL injection or SSRF probably is, and the agent's job is to confirm
it against a running target and attach proof. This turns "137 findings" into "9 confirmed exploitable".
That is the single most valuable intelligence upgrade available to thinkShield, and it bounds the agent's
search space.

### Architecture on Strands

A `Graph` of four agents, each with its own narrow toolset:

1. **Planner.** Reads SAST findings, the dependency inventory and the target's OpenAPI spec, and emits
   hypotheses. No network tools.
2. **Recon.** Runs passive and low-impact discovery (HTTP requests, crawling, spec-driven endpoint
   enumeration) only against in-scope hosts.
3. **Validator.** Attempts a minimal proof per hypothesis, such as a time-based or boolean SQLi probe, an
   SSRF to a canary host we own, or reflected XSS with a benign marker. Every intrusive action is gated by
   an interrupt that requires human approval, unless the project has pre-approved that action class.
4. **Reporter.** Turns confirmed evidence into `Finding` records with request/response proof, linked to
   the originating SAST finding. It reuses `report_ingestion_service` so the CI exemptions and lifecycle
   rules apply unchanged.

### Guardrails that must be enforced in code, not in the prompt

- **Authorization first.**
  - A target is only scannable after the project proves control of it with a DNS TXT record or a
    well-known file, the same model as domain verification.
  - Each run carries a signed scope (hosts, ports, time window, allowed action classes) recorded in the
    audit log.
  - With no verified scope, no run happens.
- **Scope enforced at the network layer.** Enforce scope with the sandbox's egress allowlist; prompt
  instructions are not enough. A prompt-injected agent must be physically unable to reach anything else.
- **Never-allowed actions.** Hard-coded deny:
  - destructive payloads;
  - DoS and load testing;
  - credential brute force;
  - lateral movement;
  - persistence;
  - data exfiltration beyond the proof marker.

  Every tool call passes through a `BeforeToolCallEvent` policy check that can cancel it.
- **Budgets.** Request-rate caps, request counts, wall clock and token limits per run, plus a kill switch
  on the run document that the hook checks before every tool call.
- **Staging targets by default.** Production targets require an explicit admin opt-in.

### Sandbox on Azure

Strands' `DockerSandbox` needs a Docker socket, which Azure Container Apps does not expose. Two options:
**Azure Container Apps Jobs** (an ephemeral container per run, its own managed identity with no portal
secrets, network egress restricted), or **Azure Container Apps dynamic sessions with custom containers**
(Hyper-V isolated, per-session). Either becomes a custom Strands sandbox class, about 150 lines. Verify
dynamic-session custom-container availability in our region before choosing it. The same sandbox can
later run builds and tests for Auto-Fix, which closes the gap that patches are currently checked only by
re-scanning, never by compiling.

Note for legal and compliance review: active testing creates exposure under the Computer Misuse Act, the
CFAA and similar laws, and under customer MSAs. The written-authorization model above should be reviewed
by counsel before release.

## 6. Recommendations, in order

1. **Instrument first (1 to 2 days).**
   - Add `job_id`, `finding_id`, `step` and `trace_id` to `AIUsageEvent`.
   - Compute fix acceptance rate, re-scan pass rate and critic agreement from data we already store.
   - Without this baseline no migration claim can be verified.
2. **Fix the quality bugs (2 to 3 days).**
   - Send a bounded code snippet in analysis.
   - Stop copying `is_false_positive` across a rule group: keep explanations shared, but judge false
     positives per file, or at least per test-versus-production path.
   - Fix the two `get_active_config()` calls.
   - Diff `compute_diff` against the real file.
   - Move critic issues into the untrusted wrapper.
3. **Efficiency in the current stack (3 to 5 days).**
   - Prompt caching (`cache_control` on the system prompt, tools and history prefix for Anthropic;
     automatic for OpenAI).
   - Continue the conversation on "revise".
   - Replace whole-file reads with excerpt-first reads, and trim old tool outputs.
   - Run 2 to 3 findings concurrently per job.
   - Set the per-finding wall clock above the retry envelope.
   - Add a per-feature model option, with a cheap model for the critic, overview, synthesis and narrator.
4. **Evals harness (1 week).** Build a golden set of about 50 real findings with known-good fixes and
   known false positives from our own repos. Run it in CI on prompt or model changes and track pass rate,
   cost and turns. Use `strands-agents-evals` only if its judges work with non-Bedrock models; otherwise a
   small pytest harness is enough.
5. **Strands spike on the validator agent (2 weeks).**
   - Pin the version.
   - Use Azure OpenAI through `LiteLLMModel` and confirm structured output works (issue #1076).
   - Write `AIUsageEvent` and the budget hard stop from model-call hooks.
   - Build the Azure sandbox class.
   - Treat this as the go/no-go on the SDK.
6. **If the spike holds, migrate Auto-Fix's loop to Strands**, keeping our tools, path guards, approval
   flow and apply service unchanged. Leave the single-shot features on `llm_client`.
7. **Ship exploit validation as a project-level opt-in**, behind domain verification and admin approval,
   with staging targets only in the first release.

## 7. Sources

- Strands docs: https://strandsagents.com/latest/documentation/docs/ (model providers, structured output,
  conversation management, hooks, interrupts, multi-agent, traces and metrics, sandbox).
- PyPI `strands-agents` and `strands-agents-evals` metadata, checked October 31, 2026.
- Azure structured-output issue: https://github.com/strands-agents/sdk-python/issues/1076
- Advisories: https://advisories.gitlab.com/pkg/pypi/strands-agents/
- Cyber-AutoAgent, an archived open-source pentest agent built on Strands:
  https://github.com/westonbrown/Cyber-AutoAgent
- AWS Security Agent multi-agent pentest architecture (does not state it uses Strands):
  https://aws.amazon.com/blogs/security/inside-aws-security-agent-a-multi-agent-architecture-for-automated-penetration-testing
- Code references in sections 2 and 3 are to `backend/app/services/` as of commit `0603d6a`.

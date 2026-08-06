The current architecture, as implied by the code layout, looks mostly like:

scan produces findings
AI analysis job is enqueued
LLM enriches findings
fix proposal is stored/displayed
That is useful, but compared to a Harmony-engine-style agent framework, it is missing some important properties:

1. No explicit multi-step reasoning state

You have AIAnalysisJob and result models, but nothing in the structure suggests a stage machine like:

intake
context gathering
hypothesis generation
patch drafting
validation
refinement
final proposal
A harmony-style agent benefits from a task graph / stage graph rather than a single analysis call.

2. No evidence-driven context assembly layer

The system appears to enrich findings, but I don’t see a dedicated layer that assembles:

finding metadata
source snippet
surrounding file context
related findings
repo/project history
prior fix attempts
policy / coding standards
That context pack is crucial. A good auto-fix agent should not prompt the model with only the finding description.

3. No verification loop

A true agentic fix framework should not stop at “proposed fix.” It should try to verify:

does the patch satisfy the finding?
does it preserve behavior?
does it introduce new issues?
is it consistent with project patterns?
Right now, the structure suggests output generation, but not a feedback loop.

4. No patch execution boundary

I see models and services for AI output, but not a clearly separated:

patch planner
patch generator
patch validator
patch applicator
That separation is important for safety and debuggability.

5. No persistent memory or learning layer

You have usage and job tracking:

ai_usage_event.py
ai_analysis_job.py
But I don’t see a memory layer for:

successful fix patterns
common false positives
project-specific conventions
provider/model performance per fix type
That’s a big gap if you want the system to improve over time.

What a Harmony-engine-style upgrade should look like

You should evolve this into a multi-agent / multi-stage orchestrator with explicit roles.

Recommended agent roles

1. Triage agent

Purpose:

classify finding severity
decide if auto-fix is appropriate
reject unsafe or ambiguous cases
Input:

finding
severity
scan context
file type
confidence score
Output:

auto_fix_candidate: true/false
fix_strategy
risk_level
2. Context agent

Purpose:

collect all relevant code and metadata
build a structured fix context
Input:

finding
repo/project info
file path
related findings
Output:

context bundle with:
offending code
surrounding lines
dependency usage
existing patterns in repo
relevant tests
3. Patch planner

Purpose:

break the fix into steps
decide whether the issue can be fixed with a minimal diff or needs broader changes
Output:

patch plan
files to edit
expected test impact
4. Patch generator

Purpose:

draft the actual code fix
preferably generate a structured diff, not free-form prose
Output:

proposed patch
explanation
assumptions
5. Validator agent

Purpose:

critique the patch
check for regressions, correctness, style, security, and alignment with the finding
Output:

pass/fail
issues
refinement instructions
6. Test synthesizer / test runner

Purpose:

generate or update tests
verify against unit/integration expectations
Output:

test suggestions or test updates
validation result
7. Finalizer

Purpose:

decide whether to store as approved fix proposal, pending review, or rejected
Concrete improvements you can make in your codebase

1. Replace single-shot analysis with a state machine

Your AIAnalysisJob model is already a good place to extend lifecycle tracking.

Add stages like:

queued
triaged
context_collected
planned
patched
validated
test_failed
needs_review
approved
rejected
This gives you observability and retry control.

2. Create a structured fix context object

Instead of sending raw finding data into llm_client, create a dedicated context schema containing:

finding details
source excerpt
file metadata
project conventions
nearby code
scan history
previous AI attempts
confidence/risk metadata
This will materially improve patch quality.

3. Split insights from fix proposals

Right now you have:

AIFindingInsight
AIScanInsight
AIFixProposal
That is good, but I’d sharpen the boundaries:

Insight = explain the issue
Proposal = recommend a fix
Patch = actual code change candidate
Validation report = critique and test outcome
That makes the flow more agentic and easier to audit.

4. Add critique-before-commit

Before a fix is shown as “ready,” run a second pass that answers:

does this patch really eliminate the vulnerability?
could it break callers?
does it fit the code style and patterns?
is there a simpler fix?
This can be the same model or a different provider/model via llm_client.py, but it should be a separate stage.

5. Add repository-specific memory

Store successful fix patterns by:

repo
language
scanner rule
fix class
provider/model
outcome
Then reuse those patterns in future fixes. This is one of the biggest “agent framework” upgrades you can make.

6. Tighten provider selection

You already manage AI providers in:

ai_provider_config_service.py
ai_provider_config.py
frontend settings page
Use that to route tasks by type:

cheap/fast model for triage
stronger model for patch drafting
maybe a second model for validation
That gives you a true model orchestration layer instead of a single provider call.

7. Add deterministic guardrails before LLM calls

Before you even ask the model:

reject unsupported file types
reject findings without enough context
reject dangerous change classes
require minimum confidence for auto-apply candidates
That reduces garbage-in/garbage-out.

8. Add artifactized outputs

Have each stage emit a persisted artifact:

triage result
context bundle
plan
patch
critique
test result
That makes debugging far easier than inspecting one blob of AI output.

The biggest missing piece: validated patch generation

If your goal is “AI auto-fix code found by scan,” the key upgrade is not just better prompting. It is closed-loop patch validation.

A Harmony-style framework would treat the agent as:

observe → reason → plan → act → verify → refine

Right now your system looks closer to:

observe → reason → emit proposal

That is the core gap.

Prioritized roadmap

Highest priority

Add explicit job stages to AIAnalysisJob
Introduce a structured context bundle
Split proposal generation from validation
Add a patch/test feedback loop
Medium priority

Add repository-memory of successful fixes
Route tasks to different providers/models by stage
Persist stage artifacts for debugging and analytics
Lower priority

Add multi-agent decomposition with separate prompt/tool contracts
Add self-refinement based on past failures
Add cross-repo fix pattern reuse
Best practical shape for your system

The best version of your flow would be:

Scan finding enters
Triage agent decides whether auto-fix is safe
Context collector gathers code and project signals
Planner decides the fix strategy
Generator drafts the patch
Validator critiques the patch
Test runner checks the fix
Finalizer stores fix proposal and status
Memory layer records outcome for future fixes
If you want it to feel like a real agent framework

Make these design choices:

every stage has a dedicated input/output schema
every stage is persisted
every stage can fail independently
no stage directly mutates state without an explicit transition
final fix proposals are always backed by validation evidence
That is the big leap from “AI feature” to “agent system.”
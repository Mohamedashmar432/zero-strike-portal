Recommended architecture

Your existing platform already has the right foundations:

MongoDB-backed scan/report storage via Report, Finding, and Scan
AI analysis pipeline via AIAnalysisJob, AIFindingInsight, and AIScanInsight
AI provider abstraction via AIProviderConfig and llm_client
Repo connectivity via ProjectRepo, RepoCredential, and OAuthConnection
Authorization boundaries via project_service.require_member(...) and API-key-scoped scanner flows
Frontend AI surfaces already showing AI analysis status and provider settings
The dedicated agent should extend this architecture, not replace it.

Target system architecture

1) User initiates remediation

From the scan detail page or project scan view, a user clicks:

“Generate Fix Plan”
“Create Auto-Fix PR”
“Review AI Patch”
This action creates a remediation request tied to:

project_id
scan_id
optionally finding_id or a set of findings
2) Remediation orchestrator service

Add a new backend service, e.g.:

ai_remediation_service
ai_remediation_job_queue
ai_remediation_agent
This service is responsible for:

loading the latest scan report
loading relevant Finding/Report data from MongoDB
resolving the target repository and branch
assembling context for the agent
dispatching work to a background job
This should be job-based, not synchronous.

3) Context builder

Before the agent runs, a context builder prepares a safe, bounded package:

Inputs

latest scan report from Report
relevant findings from Finding
scan metadata from Scan
repo metadata from ProjectRepo
repo credentials or OAuth connection references
optional code snippets from the repository around affected files
Outputs

normalized issue bundle
code context bundle
policy constraints
allowed file scope
patch budget / token budget
This context builder should enforce:

max file count
max snippet size
repo path allowlist
no secrets in prompt context
no raw tokens in agent memory
4) Repo context access layer

The agent should not get broad repository access directly. Instead, introduce a repo context tool layer with tightly scoped actions:

list branches
fetch file contents
fetch file excerpts
compute diff
create branch
commit patch
open PR
This layer is the boundary between the LLM and Git provider.

5) Agent reasoning + patch generation

The agent uses an OpenAI-compatible framework to orchestrate:

problem understanding from scan report
codebase inspection
patch proposal generation
test awareness
risk scoring
PR description generation
This is where a framework such as an OpenAI-compatible function-calling agent works well. The framework should support:

tool calling
structured outputs
retries
step limits
traceability
6) Patch validation gate

Before anything is committed:

run static validations
run unit tests if available
run lint/type checks if available
re-scan modified files if feasible
confirm the patch only touches allowed files
Only after passing these gates should the system create a branch/commit.

7) Branch + PR creation

Once validated:

create a dedicated remediation branch
apply commits
open a PR
attach:
linked scan/report
findings addressed
rationale
validation results
risk notes
explicit human-review requirement
8) Human approval workflow

The UI should show:

proposed diff
affected findings
confidence
test results
PR link
status: drafted / validated / waiting approval / merged / rejected
This is important: the agent should be assistive, not autonomous in merge authority.

Architecture diagram

flowchart LR
    U[User / Security Analyst] --> FE[Frontend: Scan Detail / Auto-Fix UI]

    FE --> API[FastAPI Backend]
    API --> AUTH[Auth / Project Membership Checks]
    API --> RS[Remediation Service]

    RS --> DB1[(MongoDB: Scan / Report / Finding)]
    RS --> DB2[(MongoDB: AI Jobs / Insights / Fix Proposals)]
    RS --> CFG[(AIProviderConfig / Encrypted Key Store)]

    RS --> Q[Durable Job Queue]
    Q --> AG[Dedicated AI Remediation Agent]

    AG --> CB[Context Builder]
    CB --> DB1
    CB --> REP[Repo Access Layer]

    REP --> GIT[GitHub / Azure DevOps]
    AG --> LLM[OpenAI-Compatible Model Provider]

    AG --> VAL[Validation Runner]
    VAL --> REP
    VAL --> DB2

    AG --> PR[Branch + Commit + PR Creator]
    PR --> GIT

    AG --> OUT[Fix Proposal / PR Metadata]
    OUT --> DB2

    FE <-- API
    FE <-- PR

How this aligns with the existing architecture

Your current system already has these patterns:

Existing AI pipeline

ai_analysis.py and ai_analysis_service.py already use job-based AI work
AIAnalysisJob provides a durable queued model
AIFindingInsight and AIScanInsight persist AI outputs separately from scan data
The remediation agent should reuse this same queued, persistent, auditable model.

Existing repo integration

project_repo_service.py, repo_credential_service.py, and OAuth/PAT support already handle repo access
connections.py and repo_credentials.py provide the repo identity plumbing
The new agent should sit on top of those services and never bypass them.

Existing AI provider abstraction

ai_provider_config_service.py
llm_client.py
AIProviderConfig model
frontend provider settings UI
So yes: use an OpenAI-compatible agent framework, but route it through your existing provider abstraction so the backend controls:

provider choice
API key storage
usage accounting
failover policy
Recommended backend components

A. ai_remediation_service

Responsibilities:

create remediation requests
fetch scan/report/finding data
prepare agent context
track status
persist outputs
B. ai_remediation_job

Mongo document, similar in spirit to AIAnalysisJob:

project_id
scan_id
finding_ids[]
status
created_at
started_at
completed_at
requested_by
branch_name
pr_url
confidence
review_state
C. ai_fix_proposal

You already have this model. Use it as the durable output object for proposed patches. It is explicitly a reviewable diff artifact, which is exactly what you want before PR creation.

D. repo_tooling_layer

A dedicated adapter for:

GitHub
Azure DevOps
branch creation
file reads
commit operations
PR creation
This layer should be the only thing the agent can call for repository actions.

E. agent_runtime

A separate worker process or service that:

executes the OpenAI-compatible agent loop
uses strict tool permissions
enforces step/time/token limits
emits structured logs and traces
Suggested data flow

User selects a scan/finding and requests remediation
API verifies project membership and permission
Backend creates remediation job
Worker dequeues job
Worker loads latest scan report from MongoDB
Worker fetches code context from repo
Agent produces patch candidates
Validation layer runs checks
If valid:
create branch
commit patch
open PR
Persist fix proposal and PR metadata
UI presents diff for approval
Security concerns you must design for

This is the critical part. A remediation agent with repo access is a high-risk system.

1) Prompt injection from repository content

Repository code and comments can contain hostile instructions aimed at the agent.

Controls

treat repo text as untrusted input
isolate system prompts from repo content
never let code override tool policy
use structured tool calling only
strip or sandbox instructions embedded in code/comments
2) Secret exposure in prompts or logs

The agent may pull files containing secrets, keys, or tokens.

Controls

secret scanning before context injection
redact secrets from snippets
never log raw prompt payloads
never expose PATs, OAuth tokens, or decrypted API keys to the LLM
keep secrets only in the repo access tool layer
3) Over-broad repo permissions

If the agent gets full write access, blast radius becomes large.

Controls

read-only by default
write access only for branch creation and commit on scoped repos
least-privilege GitHub/Azure DevOps credentials
repo-scoped and project-scoped authorization checks
4) Unsafe code changes

The agent can generate patches that break builds or introduce vulnerabilities.

Controls

validation gate before commit/PR
test execution in isolated environment
patch scope limits
require human approval for merge
confidence thresholds for auto-PR creation
5) Cross-tenant data leakage

If multiple projects/users exist, the agent must never mix context across projects.

Controls

every job must be pinned to project_id
enforce project membership at API and worker levels
never reuse context across jobs
keep repository identity isolated per project
6) LLM provider compromise or misconfiguration

Using a provider incorrectly can leak code to an external system.

Controls

admin-only provider configuration
encrypted API keys
explicit policy for which providers can handle source code
allow self-hosted models for sensitive repos
per-provider audit and usage tracking
7) Agent tool abuse

If tools are too powerful, the model can do too much.

Controls

allowlist tools
hard boundaries on branch/commit/PR operations
no arbitrary shell execution unless fully sandboxed
no network access beyond approved endpoints
no filesystem access outside the clone workspace
8) Unauthorized PR creation or code modification

A malicious user could request remediation against a repo they don’t control.

Controls

project membership enforcement
repository ownership/reachability checks
token revalidation before write actions
audit every branch/PR action
9) Unbounded cost and runaway jobs

Agents can loop, retry, or generate excessive LLM usage.

Controls

token budgets
step budgets
timeout limits
queue concurrency controls
usage metering per project
fail-fast on repeated invalid outputs
10) Auditability and incident response

You need to answer: who asked for this change, what context was used, what branch was created, what model generated it?

Controls

immutable audit log
job trace IDs
persisted prompt/response metadata, not raw secrets
PR linkage to scan and job ID
Strong recommendation on framework choice

Yes, use an OpenAI-compatible agent framework.

Best fit characteristics:

function/tool calling
structured outputs
provider portability
easy swap between OpenAI, Anthropic, self-hosted, or local models
support for multi-step agent orchestration
What matters more than the framework itself is that you wrap it in:

strict tool permissions
secure context assembly
durable job state
validation gates
audit logging
Best-practice operating model

I would implement this as human-in-the-loop by default:

Agent can analyze and propose
Agent can open a branch and PR
Agent cannot merge
Agent cannot write outside the scoped repository
Agent cannot access raw secrets
Agent cannot exceed policy constraints without admin approval
That gives you automation without losing control.

Short answer: what to build first

Build these in order:

Remediation job model
Context builder for report + repo
Repo tool layer
Agent worker with OpenAI-compatible tool calling
Patch validation gate
Branch/PR creation
Review UI
Audit + policy controls
If you want, I can turn this into a production-grade reference architecture with:

service boundaries
Mongo document shapes
API endpoints
agent tool schema
and a more polished diagram for the deck.

Recommended architecture

This should be a new remediation workflow/service, not just a small extension of the existing scan analysis flow.

Why

Scan analysis answers: What is the issue?
Remediation answers: What exact code change should we make, and can the user approve it safely?
Those are operationally different jobs, even if they reuse the same repo context, AI provider config, job queue, and findings model.

Reuse existing platform pieces

Reuse:

repo connection model
project membership and authorization
AI provider settings
durable job queue patterns
findings / AI insight storage concepts
audit logging
Add:

remediation job state machine
remediation workspace lifecycle
fix proposal + diff storage
chat scoped to a finding or remediation session
approval/apply actions
cleanup and stale workspace recovery
How the flow should work

Scan completes

Findings are stored.
Scan workspace is destroyed.
User clicks Auto-Fix

API creates a remediation job.
A fresh repo clone is created in a separate remediation workspace.
Dedicated remediation agent runs

It loads the findings and relevant repo context.
It maps findings to code locations.
It generates proposed fixes and diffs.
User reviews proposals

The UI shows a split diff view.
The user can chat with the AI for clarification.
Each finding has its own review state.
User explicitly applies a fix

No writeback happens before approval.
The system applies the patch / prepares commit / PR-style change.
Audit logs are recorded.
Cleanup

Temporary remediation workspace is deleted.
UX behavior to support

At the top of the Auto-Fix view, show:

total findings
auto-fixable findings
manual-review findings
proposed / approved / applied / failed counts
Per finding:

original code on the left
AI suggested change on the right
explanation of why the finding is addressed
confidence / limitations
clarification chat
apply button
If the repo is too large or the finding lacks enough context:

mark it as manual review
explain why it cannot be safely auto-fixed
Safety and access control requirements

The implementation must enforce:

temporary clone only
least-privilege repo access
workspace cleanup
approval required before writeback
audit every action
no silent pushes by the agent
project membership checks before access
The remediation agent must never directly modify the source repo without explicit user approval.

Why cloning again is the right approach

Cloning again for remediation is better than reusing the scan workspace because:

the scan workspace is disposable and optimized for analysis
remediation needs a stable, isolated workspace for editing and review
cloning again avoids coupling scan state to user-facing patch generation
if remediation fails, the original scan context stays untouched
Tradeoffs

extra clone time
extra storage
extra latency before first suggestion
extra compute/network cost
That cost is acceptable because this is security-sensitive code change generation, where correctness and isolation matter more than minimizing clone overhead.

Failure cases to handle

The architecture should account for:

partial fixability
missing context
stale repo state
merge conflicts
unsupported file types
large repos with many findings
fixes that need broader codebase awareness than one file
For these cases, the system should:

mark the finding as manual review
explain why it could not be safely auto-fixed
avoid forcing an unsafe patch
Mermaid architecture diagram

flowchart TD
  U[User] --> FE[ZeroStrike Portal UI]
  FE --> API[Backend API]

  API --> Q[Remediation Queue]
  API --> MDB[(MongoDB)]
  API --> AUD[Audit Log]

  Q --> ORCH[Auto-Fix Orchestrator]
  ORCH --> WS[Workspace Manager]
  ORCH --> GIT[Git Provider Integration]
  ORCH --> AGENT[Dedicated Remediation Agent]
  ORCH --> CFG[AI Provider Config]

  WS --> CLONE[Temporary Repo Clone]
  CLONE --> AGENT

  AGENT --> LLM[LLM Provider]
  AGENT --> DIFF[Diff / Patch Generator]
  AGENT --> PROP[Fix Proposal Builder]
  PROP --> MDB

  FE --> REVIEW[Split Diff Review UI]
  REVIEW --> API
  API --> APPLY[Approval / Apply Fix]
  APPLY --> ORCH
  ORCH --> PATCH[Patch Apply / Commit / PR Prep]
  PATCH --> GIT

  ORCH --> CLEAN[Workspace Cleanup]
  CLEAN --> WS

  MDB --> FE
  AUD --> MDB

Mermaid sequence diagram

sequenceDiagram
  actor User
  participant UI as Portal UI
  participant API as Backend API
  participant Queue as Remediation Queue
  participant Orchestrator as Auto-Fix Orchestrator
  participant Workspace as Workspace Manager
  participant Git as Git Provider
  participant Agent as Remediation Agent
  participant LLM as AI Provider
  participant DB as MongoDB
  participant Audit as Audit Log

  User->>UI: Click Auto-Fix on scan results
  UI->>API: Start remediation job
  API->>DB: Create remediation job record
  API->>Queue: Enqueue remediation task
  API->>Audit: Record job start

  Queue->>Orchestrator: Claim job
  Orchestrator->>Workspace: Create isolated remediation clone
  Workspace->>Git: Clone target repo at selected ref
  Git-->>Workspace: Repo contents
  Workspace-->>Orchestrator: Workspace ready

  Orchestrator->>Agent: Load findings + repo context
  Agent->>LLM: Analyze code and propose fixes
  LLM-->>Agent: Proposed remediation plan
  Agent->>DB: Save fix proposals and review states

  Agent-->>UI: Job ready for review
  User->>UI: Open per-finding split diff
  UI->>API: Fetch proposal + diff + chat context
  API-->>UI: Return proposed fix

  User->>UI: Ask clarification in chat
  UI->>API: Send chat message
  API->>Agent: Continue scoped clarification loop
  Agent->>LLM: Respond with explanation
  LLM-->>Agent: Clarification
  Agent-->>UI: Return answer

  User->>UI: Click Apply Fix
  UI->>API: Approve apply action
  API->>Orchestrator: Apply approved patch
  Orchestrator->>Workspace: Apply patch locally
  Orchestrator->>Git: Create commit / PR branch / PR
  Git-->>Orchestrator: Apply result
  Orchestrator->>DB: Persist apply status
  Orchestrator->>Audit: Record approval and apply event
  Orchestrator->>Workspace: Cleanup temporary clone

Implementation notes

Use a new remediation workflow/service layered on top of the existing scan and AI analysis foundation.
Reuse existing AI provider configuration and queue patterns.
Store remediation job state separately from scan jobs.
Track per-finding review states: pending, proposed, approved, applied, failed.
Scope chat to either a single finding or the full remediation session.
Default to PR-style review behavior before any fix is applied.
Cleanup temporary workspaces aggressively and log every action.
Final recommendation

Build the auto-fix feature as a separate remediation pipeline with:

isolated cloned workspace
dedicated remediation agent
diff-based review UX
explicit approval/apply step
full audit trail
That is the safest and most product-aligned design for this workflow.
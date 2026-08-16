What user problem exists?

Today the app already helps users see scans, findings, AI analysis, and auto-fix proposals, but the compliance section is only a preview. Your users want a higher-level answer:

“Are we aligned with framework X?”
“Which controls pass or fail based on current repo findings?”
“What should we fix first?”
That is a real gap between raw vulnerability data and audit-ready compliance reporting.

Why it matters

Users don’t want to manually translate dozens or hundreds of findings into GDPR / HIPAA / SOC 2 / ISO/IEC 27001 / ISMS controls. That translation is slow, inconsistent, and hard to defend in reviews. A compliance audit layer turns existing scan data into a control-oriented outcome that compliance, security, and engineering can act on.

What the codebase already gives you

This repo already has the right building blocks:

Project-scoped findings and reports
backend/app/routers/scans.py exposes scan report and findings retrieval.
backend/app/services/report_ingestion_service.py and backend/app/models/finding.py already model vulnerabilities in a structured way.
Async AI job pattern
backend/app/routers/ai_analysis.py
backend/app/models/ai_analysis_job.py
backend/app/services/ai_job_queue_service.py
frontend/lib/api/ai.ts
frontend/components/scans/ai-status-badge.tsx
Existing UX patterns for wizard + long-running job
frontend/app/(dashboard)/projects/[projectId]/scans/new/page.tsx
frontend/app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx
frontend/app/(dashboard)/settings/auto-fix/page.tsx
Compliance tab is already stubbed
frontend/components/projects/project-compliance-tab.tsx
frontend/components/projects/project-compliance-frameworks-section.tsx
These already show that compliance is intended to be a first-class project section.
Best flow for this feature

The best fit is:

1. User opens Project → Compliance

Show:

OWASP summary, which already exists as a compliance-adjacent view
a “Run Audit” CTA
previous audits with status, framework, and timestamp
2. User launches a wizard

Wizard steps:

Select framework(s): GDPR, HIPAA, SOC 2, ISO/IEC 27001, etc.
Select scope:
entire project
all repos
specific repo(s)
latest scan only vs all historical findings
Optional audit depth:
evidence-only
control mapping
remediation suggestions
Confirm and run
3. Backend creates an async audit job

This is the important part. Don’t run this synchronously in the request thread.

Model it like your existing AI jobs:

queued
in_progress
completed
failed
That lets the UI poll and render progress with the same patterns already used for scan AI analysis and auto-fix.

4. Audit engine pulls project findings and maps them to controls

The audit job should:

collect all relevant project findings across scans/repos
normalize them into a canonical evidence set
map each finding to one or more control checks for the selected framework
produce:
control status: pass / fail / partial / not-applicable
rationale
evidence references
suggested fixes
5. Results page

Show:

framework summary score
control-by-control table
pass/fail badges
finding evidence
remediation suggestions
exportable report
What agent flow is best?

Use a two-layer agent flow, not one giant “audit agent”.

Layer 1: Deterministic control evaluator

This layer should be rules-based and reproducible.

Purpose:

map framework controls to evidence categories
evaluate pass/fail from current findings
avoid hallucinated compliance claims
This is the core compliance engine.

Layer 2: LLM auditor assistant

Use AI only to:

explain why a control failed
summarize evidence in plain language
suggest remediation actions
generate auditor-style narrative
This is similar to how the current AI analysis and auto-fix systems already separate structured job state from generated insights.

That split is important because compliance needs traceability. If the system says a control failed, it must be explainable from findings, not just an LLM opinion.

Tradeoffs

Good

Reuses the repo’s existing async job patterns
Fits current UI conventions
Scales to large projects because it can run in background
Keeps compliance results explainable and auditable
Hard parts

Framework mapping is not one-to-one. One finding can support multiple controls.
Some controls cannot be inferred from code findings alone. For example:
access reviews
vendor management
incident response process
retention policies
GDPR/HIPAA/SOC 2/ISMS include process and organizational controls, not just code vulnerabilities.
So the product should clearly separate:

code-backed controls: assessed from findings/scans
policy/process controls: assessed from uploaded evidence or manual attestation
unsupported controls: marked “needs manual review” instead of fake pass/fail
That will make the feature trustworthy.

How it should evolve

Start with:

framework catalog
control mapping layer
project-wide findings aggregation
audit job orchestration
results UI
Then evolve into:

evidence uploads
manual attestation workflow
recurring scheduled audits
audit history and trendlines
template-based framework packs per industry
report export into PDF using the existing reporting patterns
What I would implement in this codebase

Use the existing compliance tab stub and add a dedicated compliance audit pipeline modeled after ai_analysis.

Backend shape

Add:

a compliance audit job model
a compliance audit router
a compliance audit service
a framework/control registry
a results model that includes:
framework
control id
control title
status
evidence
findings references
suggestion text
severity / risk weight
confidence
Frontend shape

Add:

“Run Audit” button in the compliance section
wizard modal or drawer
polling status badge
results table / dashboard
deep link to a specific audit run
Data source

Use project findings as the core input, because the repo already has:

scan findings
OWASP mapping
AI analysis on findings
project-level aggregation
Claude Code implementation prompt

Use this prompt to generate the feature in this repo:

You are working inside the ZeroStrike Portal codebase.

Goal:
Implement a new project-level Compliance Audit feature in the existing compliance section. The feature must let a user run an audit over the current project’s accumulated findings/vulnerabilities, select one or more compliance frameworks in a wizard, and receive a structured audit result with pass/fail/partial status per control plus remediation suggestions.

Important product requirements:
- This is an async long-running job, not a synchronous request.
- The audit must analyze the current project across its existing scans/findings, not just a single scan.
- The system must support framework selection in a wizard before running.
- Frameworks to support initially: GDPR, HIPAA, SOC 2, ISO/IEC 27001 / ISMS, and an extensible model for future frameworks.
- Results must show control-level status: pass, fail, partial, not_applicable, needs_manual_review.
- Results must include explanation, evidence references back to findings/scans, and suggested fixes.
- Do not invent compliance claims for controls that require human/process evidence. Mark them as needs_manual_review when the codebase cannot prove them from findings alone.
- Reuse the repo’s existing async job patterns, polling UI, and audit/report UI conventions.

Current architecture to align with:
- AI analysis jobs and polling already exist in backend/app/routers/ai_analysis.py, backend/app/models/ai_analysis_job.py, backend/app/services/ai_job_queue_service.py, frontend/lib/api/ai.ts, and frontend/components/scans/ai-status-badge.tsx.
- Project findings and reports already exist through scans and findings endpoints.
- The compliance section UI is already stubbed in frontend/components/projects/project-compliance-tab.tsx and frontend/components/projects/project-compliance-frameworks-section.tsx.
- The project already uses wizard-like flows for new scans and long-running AI-driven workflows.
- The project already has report and audit-log patterns; use those conventions.

Implementation tasks:
1. Backend:
   - Add new compliance audit data models for audit jobs, frameworks, control results, and audit reports.
   - Add a router for:
     - creating a compliance audit job
     - retrieving audit job status
     - retrieving completed audit results
     - listing past audits for a project
   - Add a service that:
     - gathers all relevant findings for a project
     - normalizes them into evidence
     - maps evidence to framework controls
     - calculates control status
     - generates remediation suggestions
   - Run the audit asynchronously using the existing job queue approach.
   - Persist results so they can be reopened later.
   - Record audit activity in the audit log.

2. Framework/control mapping:
   - Create a framework registry that is easy to extend.
   - For each initial framework, define controls in a structured way.
   - Map controls to evidence categories from the existing scanner findings model.
   - Support multiple controls per finding and multiple findings per control.
   - Keep unsupported controls explicit rather than guessing.

3. Frontend:
   - Replace the current compliance section placeholder with a real “Run Audit” flow.
   - Add a wizard/modal to pick framework(s), scope, and run options.
   - Add a job status view using polling.
   - Add a results dashboard with:
     - framework summary
     - pass/fail counts
     - control table
     - evidence references
     - suggestion panel
   - Make the UI consistent with existing dashboard component patterns, especially the AI analysis and auto-fix pages.

4. API client:
   - Add frontend API functions and types for compliance audit jobs and results.
   - Add query keys and polling helpers if needed.
   - Ensure the UI can refresh job state smoothly.

5. Tests:
   - Add backend tests for job creation, status transitions, result persistence, and access control.
   - Add frontend tests for the wizard and results rendering.
   - Cover the case where some controls are manually review-only.

6. Constraints:
   - Do not remove or break existing scan, AI analysis, auto-fix, or report functionality.
   - Keep the control evaluation deterministic where possible.
   - Use LLM output only for explanations and remediation suggestions, not for authoritative pass/fail unless backed by evidence.
   - Follow the codebase’s existing patterns for Beanie models, FastAPI routers, React Query, and component composition.

Deliverables:
- Working backend compliance audit pipeline
- Frontend compliance audit wizard and results UI
- Reusable framework/control registry
- Tests covering core behavior
- Minimal changes to existing scan and AI analysis flows

Before coding, inspect the existing AI analysis and auto-fix job patterns and mirror their architecture for compliance audits.
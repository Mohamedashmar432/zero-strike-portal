Prompt: Architect AI Analysis for the ZeroStrike Portal

You are working inside the ZeroStrike Portal codebase, a SaaS application that orchestrates security scans from a Go-based SAST scanner, with a FastAPI backend, Next.js frontend, MongoDB persistence, and existing scan/report workflows.

Your task is to design and implement an AI analysis layer that sits on top of existing scanner findings and produces:

per-finding AI insights
AI-generated fix proposals
scan-level synthesis summaries
UI surfaces for viewing AI output
workspace settings for AI provider configuration
safe fallbacks when AI is unavailable
This feature must fit naturally into the current product, which already has:

scan orchestration
report ingestion
finding storage
priority scoring
report templates
project/repository management
scan status and dashboard views
Product goal

Users should be able to open a completed scan and see AI-assisted analysis that explains:

What the finding means
Why it matters
How severe or urgent it is in context
Suggested remediation
Whether similar findings should be grouped
A scan-level summary of the most important risks
This should not replace the scanner. It should enrich the scanner output with higher-level interpretation and practical guidance.

Architecture principles

Design the AI layer so it is:

asynchronous, not blocking scan ingestion
idempotent, so repeated runs do not duplicate analysis
resilient, with safe retries and fallbacks
workspace-aware, so provider configuration can be centrally managed
scan-aware, so AI artifacts are tied to scans and findings
separable from raw findings, so the source scanner data remains authoritative
UI-friendly, so the frontend can progressively reveal AI insights without breaking existing flows
Core backend modules to introduce or extend

Use the existing backend structure and extend it around these areas:

1. AI model layer

Create or extend Mongo-backed models for:

AI finding insight: one record per finding containing the model’s interpretation, rationale, recommendation, confidence, and metadata
AI fix proposal: structured remediation suggestion tied to a finding, with status and confidence
AI scan insight: one synthesized record per scan summarizing patterns, top risks, and recommended priorities
These should persist separately from the scanner’s raw finding model so that:

raw findings remain untouched
AI can be regenerated independently
data can survive scanner re-ingestion
AI artifacts can be versioned later
2. AI orchestration service

Add a dedicated service that:

collects findings for a scan
prepares a normalized payload for the AI provider
sends requests to the provider
validates returned structured output
writes results back to the AI insight collections
updates scan-level AI status
This service should not be invoked directly from the frontend. It should be triggered from backend workflows.

3. AI provider adapter layer

Abstract the model provider behind a small interface so the application can support:

one default provider initially
future provider switching without rewriting the product
The provider layer should handle:

request formatting
response parsing
retry policy
error classification
response normalization
Do not hard-code provider-specific logic into the scan or findings modules.

4. AI settings / workspace configuration

Add workspace-level configuration for:

enabled/disabled state
provider selection
model name
temperature or response style controls if relevant
token or key reference handling
defaults and safe fallback behavior
This belongs in the same product area as other workspace settings, not as a one-off hidden config.

5. API endpoints

Expose backend endpoints for:

retrieving AI insight for a finding
retrieving AI summary for a scan
triggering or regenerating AI analysis
fetching AI settings
updating AI settings
checking AI processing state
These endpoints should respect existing authentication and project access rules.

6. Frontend surfaces

Add UI that lets users:

view AI insights inline on scan detail pages
inspect fix proposals per finding
see a scan-level AI summary section
configure AI provider settings in the settings area
understand whether AI analysis is pending, complete, failed, or disabled
The UI should degrade gracefully when AI is not configured.

Data flow to implement

Use the existing scan pipeline as the source of truth.

Expected flow

A scan completes and findings are ingested from the scanner report.
The system persists raw findings and report data first.
After ingestion succeeds, the scan is marked ready for AI analysis.
A background process collects relevant findings for that scan.
The AI provider is called with a structured prompt and a constrained schema.
The response is validated and stored as:
finding-level insight records
fix proposal records
scan-level summary record
The scan status is updated to reflect AI completion or failure.
The frontend queries AI results separately and renders them alongside the existing scan data.
Important data boundaries

Do not block scan ingestion on AI latency.
Do not make AI writes part of the scanner’s critical path.
Do not overwrite raw finding fields with generated content.
Do not assume every finding needs AI at once if batching is required.
Do not lose provenance: store provider, model, timestamp, and generation metadata.
Timing and orchestration mechanisms

The AI processing should run on a separate asynchronous path.

Recommended timing behavior

Trigger AI analysis after scan ingestion completes
Queue or schedule the task instead of processing it inline
Allow the system to mark scans as:
pending AI analysis
AI in progress
AI completed
AI failed
AI disabled
Support re-run/regeneration from the scan detail view or admin/debug path
Prevent duplicate concurrent AI jobs for the same scan
Operational constraints

The timing mechanism should handle:

scan bursts
temporary provider outages
repeated retries
partially completed AI output
scans with large numbers of findings
The system should be able to process a scan in chunks if needed, rather than requiring one huge request.

Integration points in the existing application

Anchor the AI feature into the current product at these touchpoints:

Scan ingestion

After the report ingestion step finishes, enqueue AI analysis.

Finding detail views

Add AI insight rendering near the finding content so users can compare scanner output and AI interpretation.

Scan detail page

Show:

AI summary section
AI progress state
regenerate action if permitted
list of findings with AI-enhanced callouts
Project dashboard

Optionally surface whether recent scans have AI summaries available.

Settings

Add AI provider settings alongside existing workspace settings patterns.

Audit/logging

Record meaningful AI actions such as:

AI analysis triggered
AI analysis completed
AI analysis failed
AI settings changed
This is important for traceability.

Suggested functional behavior

For each finding

AI should produce structured output such as:

plain-language explanation
exploitability context
why this is relevant in this codebase
concrete remediation suggestion
confidence level
references to evidence in the finding
optional fix proposal text
For each scan

AI should produce:

top 3–5 risk themes
most urgent findings
remediation order recommendation
recurring patterns across findings
executive-friendly summary
For settings

AI should support:

enabled/disabled toggle
provider/model selection
credential reference
fallback messaging when disabled
Validation and guardrails

Require the implementation to include:

schema validation for AI responses
strict typing for AI insight payloads
safe handling of provider failures
no leaking of secrets or tokens into prompts
no silent corruption of stored findings
no frontend assumptions that AI data is always present
If the provider response is malformed, store the failure and keep the raw scan usable.

Performance and scalability requirements

Design the AI layer so it can scale with:

many findings per scan
many concurrent project scans
repeated regeneration requests
future support for multiple AI providers
To avoid bottlenecks:

process asynchronously
store partial state
avoid reprocessing unchanged scans unless explicitly requested
keep AI payloads compact and normalized
Deliverables Claude Code should produce

When you implement this, produce:

Backend model additions
AI orchestration service
Provider adapter abstraction
API endpoints
Frontend UI integration
Settings page integration
Background trigger after ingestion
Tests for models, service behavior, and API flow
Graceful error and empty states
Important codebase context to respect

This application already has:

scan models and scan services
report ingestion logic for scanner output
finding persistence
dashboard and scan detail pages
settings pages including placeholders for future AI features
workspace/report template configuration
admin and project-level access control
audit logging
background task patterns and queue patterns
The AI architecture must extend this system, not replace it.

Implementation priority

Build in this order:

AI data models
AI provider abstraction
AI orchestration service
Background trigger after report ingestion
API read endpoints
Frontend display of AI results
Settings management UI
Regeneration action
Tests and failure handling
Acceptance criteria

The feature is done when:

completed scans can produce AI summaries
each finding can optionally show AI insight and fix guidance
AI runs asynchronously after ingestion
AI configuration is stored at workspace level
users can tell when AI is pending, complete, disabled, or failed
the product still works fully without AI configured
raw scanner data remains the source of truth
If you want, I can also turn this into:

a more technical Claude Code prompt with module-by-module implementation steps, or
a two-phase implementation prompt split into backend first, frontend second.
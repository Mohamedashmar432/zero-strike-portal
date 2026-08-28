 Remaining gaps and mockups to fix

Below is the list I would treat as mock / incomplete / configuration gap / product risk based on the code evidence.

A. Compliance config in the UI looks partly mock/incomplete

You specifically called out compliance config, and that concern is valid.

The strongest evidence is the frontend page:

frontend/components/projects/project-compliance-config-tab.tsx
This component is described as managing compliance configurations, enabling/disabling frameworks, automated audits, and notifications. But the project evidence also shows a hardening note that non-persisted policy switches are labeled “Not stored yet” and some config is still not actually wired to persistent backend behavior.

So the gap is:

UI exists
some controls appear real
but parts of the compliance policy surface are still not persisted or enforced
What to improve

Wire the config tab to a real persisted model for:

per-project enabled frameworks
scheduled/automatic audit settings
notification preferences
scope defaults
control overrides / exemptions
audit frequency
Right now, compliance evaluation is real, but the admin/project-admin configuration layer around it is not fully real.

B. General settings is a placeholder

The clearest mockup is:

frontend/app/(dashboard)/settings/general/page.tsx
Your summary says it is just a placeholder for workspace-wide defaults and preferences with an empty state saying the feature is not yet available.

This is a true gap:

no real config persistence
no workspace defaults management
no admin utility from it yet
What to improve

This should become the place for workspace-level defaults such as:

default report template
default AI provider behavior
default remediation policy
default compliance policy inheritance
default notification rules
C. Notification settings is not implemented

The page exists:

frontend/app/(dashboard)/settings/notifications/page.tsx
But the summary says the functionality is currently not implemented.

That means it is a UI shell, not a real config surface.

What to improve

If you want a serious operational product, notifications should support:

auto-fix proposal created
approval required
apply failed
compliance audit failed
quota exhausted
scanner health issues
Without this, admin/project admin configuration is incomplete because users cannot operationalize the system.

D. Project compliance config needs backend persistence clarity

There is a frontend project config tab:

frontend/components/projects/project-compliance-config-tab.tsx
But the broader backend evidence only clearly supports compliance audit execution, not full project-specific compliance policy administration.

So the likely gap is:

project-level compliance controls are surfaced
but not all are wired to a durable backend model
What to improve

Make sure project admin config can actually change:

enabled frameworks per project
audit scope defaults
automated audit triggers
notification routing
control exceptions
evidence retention policy
E. AI provider config is real, but project-level UX still needs validation

This part is mostly functional:

backend/app/services/ai_provider_config_service.py
backend/app/routers/ai_provider_config.py
frontend/app/(dashboard)/settings/ai-provider/page.tsx
frontend/components/projects/project-ai-provider-card.tsx
This is not a mock. Admins can manage providers, and tests cover lifecycle behavior.

But there is still a product gap:

it’s not obvious whether the project-level provider config fully overrides workspace defaults in every AI path
The codebase supports project-specific AI provider behavior through llm_client.py and BYOK tests, so the mechanism is real. The remaining gap is more about ensuring every product surface uses the same resolution rules.

What to improve

Make the config precedence explicit and consistent:

project-specific provider
workspace default
active global fallback
And show this clearly in the UI so admins know which setting is actually used.

F. Remediation settings are functional, but not all policy knobs are exposed

The auto-fix settings page is real:

frontend/app/(dashboard)/settings/auto-fix/page.tsx
backend/app/services/remediation_settings_service.py
The backend supports the meaningful controls:

enabled
confidence threshold
max findings per job
auto-fix findings per scan
blocking severities
That said, there are likely still missing policy knobs if you want the system to be production-safe.

Missing or likely-needed knobs

per-project override vs workspace default
allowed repositories / branch protection rules
max apply attempts
automatic fallback to manual review when validator confidence is low
dependency-bump approval rules
file/path allowlist configuration
model/provider selection for propose vs critic
whether apply can open PRs automatically or only draft them
G. Auto-fix critic behavior is functional but still has “skipped” branches

The critique stage is real and tested:

backend/app/services/remediation_critic.py
backend/tests/test_remediation_critic.py
But the frontend fix-stage-panel explicitly renders skipped/disabled/unavailable states.

That means the product handles these states, but they also reveal configuration-dependent behavior that could still be misunderstood by users.

What to improve

Expose these clearly in policy/config:

critic enabled/disabled
when dependency bumps are allowed
whether manual review is mandatory after critique failure
fallback behavior when critic provider is unavailable
H. Quota is real but still very scan-scoped

backend/app/services/auto_fix_quota_service.py enforces per-scan quotas and tracks usage by finding IDs.

That is good for cost control, but it is also a limitation:

it does not yet behave like a broader project/workspace budget system
it may be awkward for teams who want policy by project, repo, or severity tier
What to improve

Add higher-level quota policies:

project quota
workspace quota
severity-weighted quota
per-repo quota
monthly budget ceilings
I. Compliance catalog is functional but configuration-driven expansion may still be limited

backend/app/core/compliance_catalog.py is a static registry. That is fine for a first real version, but it creates a product gap:

admins cannot easily define new controls without code changes
framework expansion is likely slower than config-driven systems
What to improve

Consider moving toward:

persisted framework/control definitions
control mappings editable by admins
versioned control packs
framework enablement by workspace/project
This would make compliance config actually feel like configuration instead of hardcoded capability.

J. Some operational/admin surfaces are real, but not all are policy surfaces

These are functional admin pages:

scanner status
audit logs
data management
AI analytics
API keys
AI provider config
remediation settings
auto-fix quota approvals
But not every one of these is a true “config” surface. Some are observability or maintenance only.

The gap is that the product still lacks a unified place where admins and project admins can understand:

what settings are global
what settings are project-specific
what inherits from workspace
what is just informational
what is persisted versus preview/mock
That UX clarity matters a lot here.

3) Mockup / non-functional list to treat as gaps

Here is the clean list of items that are clearly mock, placeholder, or incomplete from the evidence:

Clearly mock / placeholder / incomplete

frontend/app/(dashboard)/settings/general/page.tsx

workspace settings placeholder
frontend/app/(dashboard)/settings/notifications/page.tsx

notification preferences not implemented
parts of frontend/components/projects/project-compliance-config-tab.tsx

compliance config surface exists, but some toggles are not fully persisted / wired
any “preview” or “not stored yet” compliance policy switches noted in the hardening docs

these are intentional UI placeholders, not full config
frontend/components/projects/project-attack-sim-tab.tsx

the summary says simulation execution is not implemented yet
backend/app/models/ai_scan_insight.py

summary says it currently serves as a schema without any service writing to the collection
not a config mock, but a dead-end data surface until something populates it
Functional but still configuration-gapped

frontend/app/(dashboard)/settings/auto-fix/page.tsx

real settings, but may still need more policy knobs
frontend/app/(dashboard)/settings/ai-provider/page.tsx

real, but needs clearer precedence and project/workspace behavior
frontend/components/projects/project-ai-provider-card.tsx

real, but could be better aligned with inherited config rules
frontend/components/projects/project-compliance-config-tab.tsx

real shell, needs stronger persistence and policy linkage
4) How to wire the remaining gaps into a real system

For compliance config

Build it as a real persisted policy object per workspace/project:

enabled frameworks
audit scope defaults
notification policy
scheduled audit settings
exception handling
evidence retention
Then connect:

project config UI
compliance audit runner
notification layer
audit history
For general settings

Use it as the workspace-default layer:

default AI provider
default auto-fix policy
default report template
default compliance policies
default notification behavior
For notifications

Make them event-driven from actual domain events:

remediation proposal created
approval requested
apply succeeded
apply failed
compliance audit completed
quota exceeded
provider unavailable
For auto-fix policy

Add explicit policy precedence:

workspace defaults
project overrides
per-scan overrides if needed
And expose:

apply PR behavior
critic enforcement
file/path restrictions
severity thresholds
retry limits
quota ceilings
5) Bottom line

What is fixed

The auto-fix pipeline itself is now structurally correct:

propose is real
apply is real
human approval is enforced
scanner validation protects against unsafe PR creation
What still needs improvement

The biggest remaining gaps are not the remediation engine anymore. They are:

mock or placeholder configuration screens
missing persisted compliance policy management
incomplete general workspace settings
unfinished notifications
policy precedence clarity across workspace/project/admin layers
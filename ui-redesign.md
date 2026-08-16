# Complete UI/UX Redesign — Existing Security Portal

You are working directly inside the existing application repository.

I have an already-developed security platform with working frontend, backend, APIs, authentication, business logic, database interactions, scanning workflows, compliance workflows, AI functionality, and other application logic.

My goal is to **completely redesign the UI and UX of the application** without breaking any existing functionality.

The current UI is not satisfactory. I want a professional, modern, developer/security-focused interface inspired by products such as GitHub, GitHub Security, Microsoft Defender, and Linear.

This is a **UI/UX modernization project**, NOT a backend rewrite.

---

# CRITICAL RULES

Before making any changes, inspect and understand the existing application.

## DO NOT BREAK

Do NOT unnecessarily modify:

* Backend logic
* API endpoints
* API request/response contracts
* Database schemas
* Database queries
* Authentication
* Authorization
* Session handling
* Business logic
* Scanning engines
* Security logic
* Compliance processing
* AI processing
* Existing integrations
* Existing workflows
* Existing functionality

If existing business logic is mixed inside UI components, preserve that logic while separating presentation where practical.

The primary objective is:

> **Change how the application looks and feels without changing what the application does.**

If you believe a functional change is necessary for UX, stop and explain the change before implementing it.

---

# PHASE 1 — FULL APPLICATION ANALYSIS

Do NOT modify files during this phase.

Inspect the entire repository.

Understand the actual application instead of making assumptions.

Identify:

## Architecture

* Frontend framework
* Backend framework
* Database
* Authentication mechanism
* State management
* Routing
* API architecture
* Component architecture
* Styling system
* UI component libraries
* Design system currently being used
* Build system
* Deployment structure

## Application routes

Find every:

* Route
* Page
* Layout
* Nested route
* Dynamic route
* Protected route
* Public route

## Application modules

Automatically determine the actual functional modules from the codebase.

For example, the application may contain modules such as:

* Security
* Vulnerability management
* SAST
* DAST
* Dependency scanning
* Secrets scanning
* Projects
* Repositories
* Scans
* Findings
* Tasks
* Code fixing
* Compliance
* Frameworks
* Controls
* Evidence
* AI usage
* AI security
* Administration
* Integrations
* Settings

DO NOT assume these modules exist.

Determine the real modules by inspecting the repository.

## Components

Identify:

* Shared components
* Layout components
* Navigation components
* Tables
* Cards
* Forms
* Modals
* Dialogs
* Drawers
* Charts
* Filters
* Search
* Tabs
* Status indicators
* Severity indicators
* Loading states
* Empty states
* Error states

## Backend dependencies

For each important page, identify:

* APIs being called
* Data being consumed
* Mutations
* Forms
* Server actions
* Hooks
* State dependencies

Determine which UI components are tightly coupled to application logic.

---

# PHASE 2 — CREATE A REDESIGN PLAN

After analysis, create a complete redesign plan.

Do NOT implement yet.

Produce:

1. Current application architecture
2. Current navigation structure
3. Current application modules
4. Current UI/UX problems
5. Proposed information architecture
6. Proposed navigation structure
7. Proposed design system
8. Proposed reusable components
9. Page-by-page redesign strategy
10. Risk assessment for UI changes
11. Recommended implementation order

The redesign should make the application feel like a cohesive **security engineering platform**, rather than a collection of unrelated dashboards.

---

# PHASE 3 — NEW DESIGN DIRECTION

Create a completely new visual identity for the application.

The design should be inspired by:

* GitHub
* GitHub Security
* Microsoft Defender
* Linear
* Modern DevSecOps platforms

Do NOT copy any company's branding, logo, exact UI, or proprietary visual identity.

Use the principles behind those products instead.

## Design characteristics

The application should feel:

* Professional
* Enterprise-grade
* Developer-focused
* Security-focused
* Technical
* Information-dense
* Clean
* Fast
* Modern
* Consistent
* Minimal
* Easy to navigate

Avoid the typical generic AI-generated SaaS appearance.

DO NOT overuse:

* Gradients
* Glassmorphism
* Huge cards
* Excessive rounded containers
* Excessive shadows
* Decorative illustrations
* Giant statistics
* Bright colors
* Unnecessary animations

The interface should look like a serious tool used every day by security engineers and developers.

---

# COLOR PHILOSOPHY

Create a consistent color-token system.

Use restrained colors for the main interface.

Security colors should communicate meaning.

For example:

* Critical
* High
* Medium
* Low
* Informational
* Success
* Warning
* Error

Do NOT use bright colors simply for decoration.

Severity colors should be consistent everywhere.

A Critical finding must look the same throughout:

* Dashboard
* Findings
* Project
* Scan
* Reports
* Tables
* Notifications

---

# DARK AND LIGHT MODE

If the existing application supports themes, redesign both themes consistently.

If theme support does not exist but can be added without affecting functionality, structure the design system so that dark/light support can be introduced cleanly.

Dark mode should be the primary visual direction.

Use dark graphite/neutral surfaces rather than pure black everywhere.

Use subtle borders and elevation.

---

# TYPOGRAPHY

Create a consistent typography hierarchy.

Define:

* Page titles
* Section headings
* Subheadings
* Body text
* Secondary text
* Metadata
* Labels
* Table text
* Code/technical text

Prioritize readability and information density.

---

# SPACING AND LAYOUT

Create consistent:

* Spacing scale
* Padding
* Margins
* Grid
* Container widths
* Sidebar dimensions
* Header dimensions
* Table density
* Form spacing

Avoid excessive whitespace that makes security data difficult to scan.

---

# NAVIGATION

Analyze the current application and redesign the navigation based on the actual modules discovered.

Use a GitHub-style developer navigation philosophy:

* Clear primary sections
* Logical grouping
* Nested navigation
* Active-state visibility
* Collapsible sections where appropriate
* Breadcrumbs where useful
* Global search where appropriate
* User/account controls
* Settings separated from operational security workflows

Do NOT blindly copy GitHub's navigation.

Create navigation appropriate for this application's actual functionality.

---

# REUSABLE DESIGN SYSTEM

Before redesigning individual pages, create or refactor a reusable UI design system.

Implement reusable components for:

* Buttons
* Inputs
* Selects
* Dropdowns
* Checkboxes
* Radio controls
* Tabs
* Badges
* Severity badges
* Status indicators
* Cards
* Tables
* Data tables
* Pagination
* Filters
* Search
* Dialogs
* Modals
* Drawers
* Tooltips
* Alerts
* Toasts
* Breadcrumbs
* Navigation
* Sidebar
* Header
* Command/search interface
* Progress indicators
* Charts
* Empty states
* Loading states
* Error states
* Confirmation states

Do not duplicate styling across individual pages when a reusable component should exist.

Use the application's existing component framework where appropriate rather than unnecessarily introducing another UI framework.

---

# INFORMATION DENSITY

This is a security engineering platform.

Important security data must be easy to scan.

Prefer:

* Tables
* Dense lists
* Filters
* Search
* Sorting
* Grouping
* Tabs
* Status indicators
* Severity indicators
* Inline actions

over excessive:

* Large cards
* Decorative charts
* Giant numbers
* Marketing-style sections

Use visual hierarchy to make important information immediately visible.

---

# CORE EXPERIENCE

The application should feel like one unified security platform.

Users should be able to understand:

* What is happening?
* What is dangerous?
* What needs attention?
* What has changed?
* What scans are running?
* What vulnerabilities exist?
* What compliance controls are failing?
* What tasks require action?
* What AI activity is occurring?
* What projects need attention?

The dashboard should answer these questions quickly.

---

# PAGE REDESIGN STRATEGY

Automatically identify the application's important pages.

Then redesign them systematically.

Prioritize:

## 1. Main dashboard / overview

The main overview should communicate:

* Security posture
* Critical findings
* High-risk findings
* Active scans
* Recent scans
* Compliance posture
* Tasks requiring attention
* Recent activity
* AI/security activity where applicable

Do not simply create a grid of colorful cards.

Create a useful security command center.

---

## 2. Findings / Vulnerabilities

Create an excellent security findings experience.

Include appropriate:

* Search
* Filtering
* Severity
* Status
* Project
* Scanner
* Assignment
* Date
* Sorting
* Bulk actions
* Finding details

Use dense, professional tables.

Finding severity should be immediately recognizable.

---

## 3. Project pages

Projects should have a clear hierarchy.

Possible structure:

* Overview
* Findings
* Scans
* Tasks
* Compliance
* Activity
* AI/security information

Use tabs or appropriate navigation based on the actual application structure.

---

## 4. Scan pages

Make scan execution and results easy to understand.

Clearly communicate:

* Scan status
* Repository
* Branch
* Commit
* Scanner types
* Progress
* Findings
* Errors
* Completion
* Historical results

Use technical/developer-oriented presentation.

---

## 5. Compliance

Create a professional compliance experience.

Show:

* Overall compliance percentage
* Frameworks
* Controls
* Pass/fail status
* Evidence
* Exceptions
* Review status
* Control details

Use tables and structured information rather than decorative cards.

---

## 6. AI Security / AI Usage

If this functionality exists in the application, create a dedicated modern experience for:

* AI usage
* Model usage
* Token usage
* Cost
* Requests
* Activity
* Security events
* Policy violations
* AI-assisted code fixing

Make this feel like part of the security platform rather than an unrelated AI dashboard.

---

## 7. Tasks

Create a clean developer/security task-management experience.

Support the application's existing functionality while improving:

* Priority
* Status
* Assignment
* Due dates
* Project relationships
* Security findings
* Workflow visibility

---

# UX PRINCIPLES

Improve the UX, not just the colors.

Look for opportunities to improve:

* Navigation
* Discoverability
* Information hierarchy
* Search
* Filtering
* Empty states
* Loading states
* Error handling
* Confirmation flows
* Form usability
* Table usability
* Bulk operations
* Keyboard interaction
* Responsive behavior

Do not add unnecessary functionality.

Improve existing workflows wherever the UI itself is the problem.

---

# RESPONSIVE DESIGN

The application must remain usable across:

* Desktop
* Laptop
* Tablet where appropriate

Prioritize desktop because this is a security engineering portal, but do not create broken responsive layouts.

Tables should have an intentional responsive strategy.

Do not simply shrink everything until it becomes unusable.

---

# ACCESSIBILITY

Maintain or improve accessibility.

Use:

* Semantic HTML
* Keyboard navigation
* Visible focus states
* Appropriate contrast
* Accessible labels
* Accessible dialogs
* Accessible forms
* Meaningful status indicators

Do not rely only on color to communicate severity or state.

---

# IMPLEMENTATION RULES

After the redesign plan is established, implement the redesign.

Work incrementally.

DO NOT rewrite the entire application in one uncontrolled operation.

Use this order:

1. Global design tokens
2. Theme
3. Typography
4. Global layout
5. Sidebar/navigation
6. Header
7. Shared components
8. Main dashboard
9. Findings
10. Projects
11. Scans
12. Compliance
13. Tasks
14. AI/security pages
15. Remaining pages
16. Settings/administration

Adapt the exact order based on the actual application discovered during analysis.

---

# IMPORTANT: PRESERVE FUNCTIONALITY

When modifying a page:

First understand what it currently does.

Then preserve:

* Existing API calls
* Existing state
* Existing data
* Existing event handlers
* Existing validation
* Existing permissions
* Existing authentication
* Existing workflows

Only change the presentation and UX unless explicitly instructed otherwise.

If a component contains both business logic and UI logic, do not accidentally delete the business logic while redesigning it.

---

# GIT SAFETY

Before major implementation:

Check the current Git status.

If the repository has uncommitted user changes:

DO NOT overwrite them.

Create a safe UI redesign branch if appropriate.

Use small logical commits where possible.

Example:

ui/redesign-system

Then commits such as:

* redesign: add design tokens
* redesign: update global layout
* redesign: update navigation
* redesign: redesign dashboard
* redesign: redesign findings
* redesign: redesign projects

---

# VISUAL QA

After implementing each major page:

Run the application.

Actually inspect the resulting UI.

Do not assume the generated code looks good.

Check:

* Alignment
* Spacing
* Typography
* Contrast
* Table density
* Navigation
* Responsive behavior
* Loading states
* Empty states
* Error states
* Overflow
* Long text
* Large datasets
* Interactive states

Fix obvious visual problems before moving to the next page.

---

# FUNCTIONAL QA

After each major redesign, verify that existing functionality still works.

At minimum verify:

* Navigation
* Authentication
* API calls
* Forms
* Search
* Filters
* Tables
* Create operations
* Update operations
* Delete operations
* Scan workflows
* Compliance workflows
* AI workflows
* Code-fix workflows
* Settings
* Permissions

If automated tests already exist, run them.

If appropriate, use the existing testing framework or browser tooling to verify important workflows.

Do not create fake/mock functionality just to make the new UI look complete.

Use the real application data and existing APIs.

---

# IMPORTANT: DO NOT INVENT FEATURES

Do not add functionality simply because it would look good.

Do not invent:

* APIs
* Data
* Metrics
* Security findings
* Compliance controls
* AI statistics
* Scanner results
* Backend capabilities

If something is not currently available, design an appropriate empty/placeholder state instead of fabricating data.

---

# FINAL QUALITY STANDARD

The final application should look like a professional enterprise security engineering platform.

The visual target is:

GitHub developer experience
+
Microsoft Defender security information density
+
Linear interaction quality
+
Modern DevSecOps tooling

But it must have its own identity.

It should NOT look like:

* A generic AI-generated dashboard
* A marketing website
* A template dashboard
* A collection of colorful cards
* A Dribbble concept that is difficult to use

It should look like a real product that security engineers could use every day.

---

# EXECUTION MODE

Follow this sequence strictly:

### STEP 1

Analyze the entire repository.

### STEP 2

Report the architecture, modules, routes, components, APIs, and current UI structure.

### STEP 3

Create the complete redesign plan.

### STEP 4

Create the new design system.

### STEP 5

Implement the global layout and navigation.

### STEP 6

Redesign the highest-priority pages incrementally.

### STEP 7

Run the application and perform visual QA.

### STEP 8

Perform functional regression testing.

### STEP 9

Fix any issues discovered.

### STEP 10

Provide a final summary containing:

* What was redesigned
* What components were created
* What pages were changed
* What functionality was preserved
* What APIs/backend logic remained untouched
* Any remaining UI/UX issues
* Any recommended future improvements

## FINAL RULE

**Do not sacrifice existing functionality for visual design.**

The objective is:

> **A completely new, polished, GitHub-inspired security platform UI/UX sitting on top of the existing working application.**

Start with **STEP 1 — analyze the repository only. Do not modify files until the analysis and redesign plan are complete.**

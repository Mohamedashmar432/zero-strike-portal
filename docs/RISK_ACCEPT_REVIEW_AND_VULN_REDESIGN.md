# Risk acceptance review, admin-sent acknowledgement, Vulnerabilities redesign

Plan by Opus 5.5, 2026-11-05. Builder: Sonnet 5.5. Tests: Haiku 5.5. Branch `feat/risk-accept-review`.
Where this doc and the code disagree, verify the code first.

## Decisions on the plan's open questions

- R1: PATCH to `open`/`in_progress` while `review.status == "accepted"` is refused with 409 ("Ask an admin to revoke the exemption"), for both kinds. Closes an exemption leak that exists today for false positives.
- R2/Q-recipients: extra recipients may be any address; the send dialog has an explicit confirm step naming the recipient count. Flag for NDA/MSA review, no compliance conclusion.
- Q1: `finding.review_requested` admin email stays as is (a request is not an approval).
- Q2: only a portal admin sends acknowledgement requests.
- Q3: a link acknowledgement does not require sign-in.
- Q4: the minimum-comment rule applies to `accepted_risk` only.

## Requirements

1. Any member may request accepted risk on any finding kind (code and SCA); the comment is mandatory (min 40 chars, >= 6 words of 2+ letters, not a placeholder).
2. New `WorkspaceSettings.risk_acceptance_review_required` (default off, admin only, no project twin) is independent of `finding_review_required`, which now governs false positives only. A startup migration seeds the new field from the old one when absent, so no upgrade loosens review.
3. Approval or auto-accept notifies the requester in-app only (`finding.review_decided` is already `emailable=False`). No automatic email.
4. An admin can email the project owner plus up to 10 extra addresses an acknowledgement request with a PDF and CSV of the risk-accepted findings. Never automatic. Token in the URL fragment, sha256-hashed, single use, 14 days, resendable (max 5, 10 min throttle). `smtp_host` unset records `not_configured`; the UI never says "sent" unless a recipient delivery is `sent`.
5. Vulnerabilities gets a "Risk accepted" tab: requested by, approved by/at, comment, acknowledged by/at/pending, batch state.
6. Vulnerabilities page redesign: faceted filters with counts, URL-synced, saved views, sortable table, bulk actions, lifecycle chips. Filter header and table above summary charts.
7. Audit rows for every step, new notification events, MCP `mark_false_positive` text, docs.
8. Migration: legacy `accepted_risk` rows with no review become `open` with a pending review (requester from the audit trail when found, otherwise no review). Never auto-accepted. Idempotent.

## Data model

- `WorkspaceSettings.risk_acceptance_review_required: bool = False`; add to schema and the router's boolean guard.
- `FindingReview` unchanged; add index `(project_id, review.kind, review.status)` on `Vulnerability`.
- New collection `risk_acknowledgements` (`RiskAcknowledgementBatch`): `project_id`, `created_by_user_id`, `created_at`, `message`, `items[]` (frozen snapshot: vulnerability_id, fingerprint, rule, severity, kind, file_path, requester and reviewer ids/emails, timestamps, comment, auto_accepted), `recipients[]` (email, is_project_owner, user_id, token_hash, token_expires_at, delivery pending|sent|failed|not_configured, send_count, last_sent_at, acknowledged_at/by/via). Batch state is derived. An item's acknowledgement only counts while `item.reviewed_at == vuln.review.reviewed_at`. Register in `db/mongo.py`.
- `validate_risk_comment` in `finding_review_service`, `MIN_RISK_COMMENT_CHARS = 40`, mirrored in the frontend.

## API

- `PATCH .../vulnerabilities/{vid}/status`: accepted_risk on any kind goes to `request_review`; owner/admin-only branch removed. Shared logic in new `services/vulnerability_triage_service.apply_status_change`.
- `GET .../vulnerabilities`: multi-value `severity,status,kind,repo`; `rule_id`, `path`, `review_state`, `review_kind`, `assignee=__none__`, `age`; sort by severity/rule/file.
- `GET .../vulnerabilities/facets` (register before `{vulnerability_id}`), `POST .../vulnerabilities/bulk` (ids <= 100, assign|status, per-item results and audit).
- `GET .../risk-acceptances` (member), `GET .../risk-acceptances/report.{pdf,csv}` (admin preview).
- `POST/GET .../risk-acknowledgements` (create is `require_admin`; member reads are masked), `.../{bid}/report.{pdf,csv}`, `.../{bid}/resend` (admin), `.../{bid}/acknowledge` (project owner).
- Public `POST /risk-acknowledgements/lookup` and `/acknowledge` (token in body, rate limit 10 per 10 min per IP, identical 404 for every bad token).

## Services, events, audit

- `kinds_allowed(vuln)` replaces `kind_allowed`; `_review_required(kind)` picks the toggle; kind-specific auto-accept comment; 409 when a pending review of the other kind exists.
- `risk_acknowledgement_service`: `eligible_items`, `create_and_send`, `resend`, `acknowledge_by_token`, `acknowledge_in_portal`, `state_for`, awaited `_send`.
- Events: `risk.acknowledgement_requested` (project audience, owner only, not emailable), `risk.acknowledged` (admin audience, in-app).
- Audit actions (avoid "member" / "user " substrings): `Risk Acknowledgement Requested`, `Risk Acknowledgement Resent`, `Risk Acknowledged`, `Risk Acknowledgement Link Expired`; existing review actions reused. Never store addresses in metadata.
- `main.py` lifespan: `migrate_risk_review_toggle()` and `migrate_unreviewed_accepted_risks()` after `migrate_unreviewed_false_positives()`.
- `email_service.send_email`: attachment subtype from extension (pdf vs csv).
- PDF: `pdf_report_service.render_risk_acceptance_pdf`, new template `reporting/templates/risk_acceptance_report.html.j2`; tables only, no `<pre>`, cp1252-sanitised, comments truncated to 1000 chars. CSV: stdlib, UTF-8 BOM, formula-injection guard.
- MCP `mark_false_positive`: use `kinds_allowed`; text points to accepted risk in the portal.

## Frontend

- Settings > General: second switch "Admin review of risk acceptance".
- Admin Finding Reviews: kind filter and column.
- Status dialog: accepted risk for every kind, live comment counter.
- Vulnerabilities page split into `components/vulnerabilities/`: tabs (All, Risk accepted via `?view=risk`), sticky `FilterChips` (roving tabindex, Backspace removes), `FacetPanel`, `VulnerabilityTable` (`aria-sort`, select-all), `LifecycleChip`, `BulkActionBar`, `ResultCount` (`aria-live`), saved views in localStorage. Pass labels as `SelectValue` children (base-ui).
- Risk accepted panel, `RequestAckDialog` (confirm step), batch strip, public `app/(auth)/acknowledge-risk/page.tsx` reading the token from `location.hash`.
- `lib/api/risk-acknowledgements.ts`, query keys, facets/bulk in `vulnerabilities.ts`.

## Work packages (in order)

WP1 toggle, kind rules, comment validation, triage service. WP2 migration. WP3 MCP text and docs. WP4 events. WP5 batch model, service, token routes. WP6 email, PDF, CSV, resend limits. WP7 list filters, facets, bulk. WP8 frontend settings/reviews/dialog. WP9 Vulnerabilities redesign. WP10 Risk accepted tab, dialog, public page.

## Test plan

pytest on mongomock for every package (toggle independence, comment rules, migration branches and idempotency, admin-only create, token single use/expiry/rate limit, `not_configured` never opens SMTP, resend rotation, masked recipients, re-accept invalidates acknowledgement, facets, bulk, severity sort, PDF with 600 rows and long comments, CSV subtype). Frontend: lint, `tsc --noEmit`, vitest. Browser QA per CLAUDE.md as admin, member and owner (refusal paths, wire assertions, zero console errors).

## Risks

mongomock may not support `$switch` in sort (fallback: Python rank for the page or stored `severity_rank`); migration shows legacy accepted-risk rows as open and pending (CI unchanged, say so in release notes); `finding_review_required` copy must change; extra recipients move finding data outside the portal.

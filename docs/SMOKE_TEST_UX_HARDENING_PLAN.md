# Smoke-test UX / behaviour hardening plan

Source: prod smoke test on 2026-10-03 (planned by Opus 5.5, built by Sonnet 5.5). Code wins over this doc if they disagree.
Decisions made by the owner: keep the `sudo rm -rf <name>` project-delete prompt unchanged; the overview proposals tile shows
"N awaiting review" / "N PRs opened" (no "ready to merge" concept exists). Registration verification and the welcome email are
out of scope (product decision pending). Mark-all-read already exists in the bell dropdown (no code needed).

Every package: unit tests + `tsc` + `ruff` + lint. Do not `npm run build` while `npm run dev` runs. Browser QA is done separately.

## WP1 - Overview card shows real data
**Backend** `backend/app/services/ai_provider_config_service.py` `get_project_usage` (~line 374): replace
`resolve_active_config(project_id)` with `chain = await resolve_failover_configs(project_id)`; `serving = chain[0] if chain else None`;
return `enabled = serving is not None`, `active_provider`/`active_model` from `serving` (None when absent).
Test `test_project_ai_usage_reports_the_provider_that_would_serve` in `backend/tests/test_project_byok.py`: BYOK off -> portal provider;
BYOK on + project key -> project provider; BYOK on, no project key -> `active_provider is None`, `enabled is False`.
Keep `backend/tests/test_project_scan_activity.py:135` green.

**Frontend** `frontend/components/projects/project-overview-hub.tsx` (~lines 400, 481-503):
- Query `listProjectAutoFix(project.id)` with `queryKeys.ai.autofix.projectList(project.id)` (shared cache with Auto-Fix tab).
- Export pure helpers `proposalCounts(items)` -> `{awaitingReview: sum item.summary.proposed, prsOpened: sum item.summary.pr_created}` and `providerLabel(aiUsage)`.
- Proposals tile: skeleton while loading; "None yet" when 0; else `${awaitingReview} awaiting review` (+ sub-line `${prsOpened} PRs opened` if >0). Delete "3 Ready to Merge".
- Model & provider tile: no provider -> "No AI provider available for this project"; else `${provider} · ${model}`. Delete the "Claude 3.5 Sonnet" fallback.
- Token tile: "—" while usage undefined, else the real total (0 is fine). Delete the "24,810" fallback.
- Compliance empty state: query `listFrameworks` (`queryKeys.compliance.frameworks()`; catalog returns only runnable set). Text:
  `Run an audit to check this project against ${titles.join(" and ")}. Results are computed from scanner findings, never estimated.` ("the supported frameworks" while loading).
- New test file `project-overview-hub.test.tsx`: empty project shows no "Ready to Merge"/"Claude 3.5 Sonnet"/"24,810", shows "None yet" and "No AI provider available"; compliance text has no PCI-DSS/HIPAA/NIST; `proposalCounts` sums across scans.

## WP2 - Small UI fixes
- **Step counter**: `frontend/components/repos/repo-connect-wizard.tsx` add optional `phaseLabel?: string` and exported `wizardTitle(step,total,phaseLabel?)` ->
  with label `${phaseLabel} (${step} of ${total})` else `Step ${step} of ${total}`; use in CardTitle (~line 248).
  `frontend/app/(dashboard)/projects/new/page.tsx` (~line 85) passes `phaseLabel="Step 2 of 2 — Connect a repository (optional)"`. Standalone `/repos/new` unchanged.
  Test in `repo-connect-wizard.test.tsx`: "embedded wizard titles itself as the second phase, not a fresh step 1".
- **Uploader name**: `backend/app/schemas/scanner_status.py` `BinaryChecklistItem` add `uploaded_by_email: str | None = None`;
  `backend/app/services/scanner_status_service.py binary_checklist()` batch-look-up uploader ids (`PydanticObjectId.is_valid` + `User.find(In(User.id, ...))`, same pattern as `routers/audit_logs.py:_label_map`);
  frontend `lib/api/scanner-status.ts` add field; `admin/scanner-status/page.tsx` (~line 142) renders `b.uploaded_by_email ?? (b.uploaded_by ? "Deleted user" : "—")`.
  Test `test_binary_checklist_names_the_uploader_by_email` in `backend/tests/test_scanner_status.py`.
- **Toasts**: admin dialog already toasts; reproduce in browser first. In `settings/ai-provider/page.tsx` create/update onSuccess order -> `reset(); onClose(); toast.success(...)`.
  Unify wording: "AI provider added" / "AI provider updated" / "AI provider deleted" (admin) and "AI provider removed" (project, `components/projects/project-ai-provider-card.tsx` ~107,125). Extend the existing create test to assert `toast.success("AI provider added")`.
- Also check `settings/ai-provider/page.tsx:~221` empty `<SelectValue />` (base-ui gotcha).

## WP3 - Confirmation dialogs
New `frontend/components/common/confirm-dialog.tsx`: props `{open,onOpenChange,title,description,confirmLabel,pendingLabel,pending,onConfirm,destructive=true}`, built like the "Delete user" dialog (`admin/users/page.tsx:333-354`), Cancel outline + destructive/default confirm. Callers keep the target label in state after close (avoid "undefined" during close animation).
| Where | Title | Description | Confirm |
|---|---|---|---|
| `settings/ai-provider/page.tsx` Delete (~437) | Delete AI provider? | "{name}" and its saved API key will be removed. [if active: It is the active provider, so AI features stop until another one is activated.] This cannot be undone. | Delete provider |
| `project-ai-provider-card.tsx` Remove (~219) | Remove this project's AI key? | "{name}" will be removed. [if active: This project will have no AI provider. AI analysis, auto-fix and compliance narratives stop until you add another key. It does not fall back to the portal's provider.] | Remove key |
| `admin/users/page.tsx` Promote (~95) | Make {email} an administrator? | Administrators can manage every user, AI provider and workspace setting. | Promote to {roleLabel("admin")} (non-destructive) |
| `admin/users/page.tsx` Demote | Remove administrator access from {email}? | They lose access to the admin pages and workspace settings. (verify against `require_admin` usage) | Demote to {roleLabel("user")} |
Users page: `UserRowActions` gets `onRequestRoleChange(user)`; mutation runs behind the dialog.
Tests: replace `page.test.tsx:332` ("Delete ... immediately") with "Delete asks for confirmation and deletes only after confirming" + "cancelling the delete confirmation deletes nothing"; new `project-ai-provider-card.test.tsx` ("Remove asks for confirmation..."); new `admin/users/page.test.tsx` ("Promote asks for confirmation...").
Project delete keeps the existing `sudo rm -rf` prompt (owner decision).

## WP4 - Audit log
- **4a project scope**: `backend/app/routers/projects.py` add `project_id=project_id` to the five `audit_service.record` calls (~574, 604, 621, 638, 665).
  Legacy rows: add `effective_project_id(log)` in `audit_service.py` = `log.project_id or (log.metadata or {}).get("project_id")` and use it everywhere `routers/audit_logs.py` reads `log.project_id` (counts, category filter, `_to_response`, project label map).
  Tests: `test_project_provider_events_are_project_scoped` (test_project_byok.py); `test_legacy_rows_scope_from_metadata_project_id` (test_audit_logs.py).
- **4b role change detail**: `backend/app/routers/users.py update_user` (~80-100): capture old role/active first; record "User Role Changed" (`metadata` email, from_role, to_role), "User Disabled"/"User Enabled" (email), "User Updated" only if nothing changed (all still classify as privilege).
  Frontend `lib/api/audit-logs.ts` add `auditDetail(log)` ("{email}: {RoleFrom} → {RoleTo}" else `metadata.email ?? null`), muted line under the action in `admin/audit-log/page.tsx` (~181).
  Tests: update `test_role_change_and_delete_are_audited` (`test_admin_user_actions.py:72`); unit test for `auditDetail`.
- **4c client IP on all request-driven events**: new `backend/app/core/request_context.py`: ContextVar holding `(asyncio.current_task(), client_ip(request), user_agent)`; `async def bind_request_context(request)`; `current()` returns `(None,None)` unless `asyncio.current_task()` is the stored task (so spawned background tasks never inherit a request's IP).
  `backend/app/main.py` (~118) `FastAPI(..., dependencies=[Depends(bind_request_context)])` (must be a dependency, NOT BaseHTTPMiddleware - different task). `audit_service.record()`: when `actor_type != "system"`, fill missing `ip_address`/`user_agent` from `request_context.current()`; explicit values win. Reuses `rate_limit.client_ip` so TRUSTED_PROXY_HOPS is respected.
  Tests (test_audit_logs.py): `test_request_driven_rows_carry_the_client_ip` (trusted_proxy_hops=1, X-Forwarded-For 203.0.113.7); `test_rows_written_from_a_spawned_task_do_not_inherit_the_request_ip`.

## WP5 - Forgot-password audit + email failure alert
- `core/notification_events.py` add event `email.delivery_failed` (audience "admin", default_in_app True, default_email False, label "Email delivery failing").
- `services/notification_service.py` `async report_email_failure(context)`: never raises, module-level monotonic throttle (once/hour), calls `notify("email.delivery_failed", title="Outbound email is failing", body=f"The portal could not send a {context} email. Check SMTP settings and the server log.", link="/settings/notifications", severity="error")`. Body never contains a recipient address.
- Call sites: `_send_emails` (count failures in `_send`, return count; report once if >0 and key != "email.delivery_failed"; thread the event key from `notify()`); `auth_service._send_template` (~100) -> "signup decision"; `auth_service.request_password_reset`: unknown/inactive -> `record("Password Reset Requested For Unknown Account", actor_type="anonymous")` (add "anonymous" to the actor_type Literal in `models/audit_log.py`, store NO email); known -> `record("Password Reset Requested", actor_user_id, target_type="user", target_id)`; send failure -> `record("Password Reset Email Failed", actor_type="system", target_id=user_id, metadata={"error": type(exc).__name__})` + `report_email_failure("password reset")`.
  Change the log line (~308) to log `user_id`, not the email address. Router response stays identical (non-enumerating).
- Tests: `test_forgot_password.py` two tests (audited for known/unknown without storing email; send failure -> same response, admin notification, failure audit row); `test_notifications.py` `test_email_failure_alert_is_throttled` (reset module timestamp), `test_report_email_failure_never_raises`.
- Known follow-up (not in scope): reset email is sent inline so known accounts respond slower than unknown (timing leak).

## Deploy config fixed during the test (prod, not code)
`SMTP_USERNAME` (code reads this, env had `SMTP_USER`), `SMTP_FROM_ADDRESS=thinkshield@visitor.thinkbridge.com`, `FRONTEND_ORIGIN` (was defaulting to localhost, so reset links and OAuth connection callbacks pointed at localhost).
Still to do by owner: rotate the SMTP password and move it to a container-app secret/Key Vault reference; remove unused `SMTP_USER`, `EMAIL_FROM`, `EMAIL_FROM_NAME` env vars.

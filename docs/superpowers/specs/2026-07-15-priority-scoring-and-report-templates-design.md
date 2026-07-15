# Priority Scoring, Executive Report Template & Enhanced Filters — Design

Date: 2026-07-15

## Goal

Three related features that share the same data model change:

1. A **priority score** on every finding (0-10, plus a critical/high/medium/low tier), independent of severity, shown everywhere findings are shown.
2. A second, visually richer **"Executive" PDF report template**, ported from the sibling `zero-strike-cli`'s `report.html.j2`, selectable per-project (with a workspace-wide default) alongside the existing plain "Standard" template.
3. **Dropdown-style filters** (severity, kind, OWASP Top-10 category, priority) on the scan report page, replacing the current toggle-button row.

## Background (current state)

- `Finding` (`backend/app/models/finding.py`) has `severity`, `confidence`, `owasp`, `cwe`, `kind` but no risk/priority score of any kind.
- The scan detail page (`frontend/app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx`) already shows a "Score" column, but it's a hardcoded severity→number lookup table explicitly commented as "Not a real CVSS score... without fabricating false precision."
- The portal already has its own PDF report pipeline: `pdf_report_service.py` renders `reporting/templates/scan_report.html.j2` (plain, tabular) via `xhtml2pdf`. This becomes the "Standard" template — unchanged.
- `zero-strike-cli/src/reporting/templates/report.html.j2` is a much richer branded template (cover page, risk banner, OWASP compliance grid with pass/fail rationale, remediation plan). It assumes fields the portal's `Finding`/`Report` models don't have under those names (`f.risk_score`, `f.recommendation`, `f.file`, `f.code_snippet`, `f.scanner`, `result.tech_stack`, `result.executive_summary`, `result.ai_provider`) and uses an OWASP A01-A10 mapping that has a **different category ordering** than the portal's own canonical `app/core/owasp.py::OWASP_TOP_10` (e.g. the CLI's A02 is "Security Misconfiguration"; the portal's A02 is "Cryptographic Failures"). The portal's mapping is treated as the single source of truth; the ported template must not introduce a second, contradictory OWASP mapping.
- Every `Settings` sub-page (`frontend/app/(dashboard)/settings/*/page.tsx`) is currently a "Coming soon" `EmptyState` stub with no backing model — including `settings/report-templates/page.tsx`, whose own subtitle already says "Customize the layout and branding of generated PDF reports." This feature fills that page in.
- `FilterBar` (`frontend/components/common/filter-bar.tsx`) already supports a `select`-type dropdown facet; it's just not used on the scan report page yet (that page has its own bespoke toggle-button row).

## 1. Priority score

Computed once, at ingestion time, in `report_ingestion_service.py` (alongside the existing `_map_finding`), using a small new pure module `backend/app/core/priority.py` (mirrors the existing `core/owasp.py` pattern):

```
severity_base   = {critical: 8.0, high: 6.0, medium: 4.0, low: 2.0, info: 0.5}.get(severity, 0)
owasp_boost     = 1.5 if finding.owasp else 0
confidence_adj  = {"high": 0.5, "low": -0.5}.get(confidence, 0)   # medium/None -> 0
priority_score  = round(clamp(severity_base + owasp_boost + confidence_adj, 0, 10), 1)
priority_tier   = "critical" if priority_score >= 8.0
                  else "high"     if priority_score >= 6.0
                  else "medium"   if priority_score >= 4.0
                  else "low"
```

This is deterministic and explainable from data the `Finding` model already carries. It deliberately lets OWASP/confidence shift a finding's priority tier independent of its severity tier (e.g. a medium-severity, OWASP-tagged, high-confidence finding reaches priority 6.0 → "high" priority despite "medium" severity).

Confidence values are lowercase `"high"`/`"medium"`/`"low"` strings (confirmed against `backend/tests/fixtures/go_report_sample.json`), matching severity's casing.

**No backfill**: findings ingested before this ships keep `priority_score = None` until their scan is re-run. `report_ingestion_service.ingest()` already deletes and re-inserts all findings for a scan on every (re-)upload, so this self-heals naturally.

### Data model

- `Finding` (`backend/app/models/finding.py`): add `priority_score: float | None = None`, `priority_tier: Literal["critical", "high", "medium", "low"] | None = None`. No new index — the existing `scan_id` index already scopes the per-scan findings query small enough that an equality filter on `priority_tier` needs no index of its own (same reasoning as the existing `severity`/`kind`/`owasp` filters on that endpoint).
- `FindingResponse` (`backend/app/schemas/report.py`) and `_to_finding_response` (`backend/app/routers/scans.py`): add `priority_score`, `priority_tier`.
- `GET /scans/{scan_id}/findings`: add a `priority: str | None` query param, filtering by `Finding.priority_tier == priority` — same pattern as the existing `severity`/`kind`/`owasp` params.

### Frontend

- `frontend/lib/api/findings.ts`: `Finding` type gains `priority_score: number | null`, `priority_tier: "critical" | "high" | "medium" | "low" | null`; `listFindings()` gains a `priority` option/query param.
- New `frontend/lib/priority.ts` (mirrors `lib/owasp.ts`): ordered tier list, labels, and tier→color-class mapping.
- Scan detail page `FindingItem`: the existing "Score" column (currently the fake `SEVERITY_SCORE` lookup) is replaced with the real `finding.priority_score`, styled by `priority_tier`; a small priority-tier badge is added next to the existing severity badge.

## 2. Report templates

### Template selection & storage

- `Project` model (`backend/app/models/project.py`): add `report_template: Literal["standard", "executive"] | None = None`. `None` means "inherit the workspace default."
- New singleton `WorkspaceSettings` document (`backend/app/models/workspace_settings.py`): `default_report_template: Literal["standard", "executive"] = "standard"`. First real backend model behind any Settings page.
- New `backend/app/routers/report_templates.py`:
  - `GET /api/v1/settings/report-template` / `PUT /api/v1/settings/report-template` (PUT gated by the existing `require_admin` dependency) — get/set the workspace default.
  - `GET /api/v1/report-templates/{template}/preview` (`template` = `standard` | `executive`) — renders that Jinja template against a small hardcoded fixture (5-6 findings spanning severities and kinds, obviously-fake project/repo names) and returns raw HTML. Powers the "small preview window" in both the Settings page and the Project Overview tab. Not project-scoped, so it never touches real data.
- `Project` create/update schemas and `ProjectResponse` gain `report_template`.
- New service `backend/app/services/report_template_service.py`: `get_effective_template(project) -> Literal["standard", "executive"]` = `project.report_template or workspace_settings.default_report_template`. Used by the real PDF-download endpoint.
- `GET /scans/{scan_id}/report/pdf`: resolves the effective template via the above and passes it to `pdf_report_service.render_scan_report_pdf`. No per-click template override — the template choice is a project/workspace setting only (report generation, not the on-screen scan page, which is unchanged).

### `pdf_report_service.py`

- `render_scan_report_pdf(scan, report, findings, template: Literal["standard","executive"])` picks the Jinja template file by name (`scan_report.html.j2` vs `scan_report_executive.html.j2`) instead of the current hardcoded name.
- New small pure helpers (used only by the executive template's render context): `_overall_risk(by_severity) -> str` (CRITICAL/HIGH/MEDIUM/LOW/NONE, same tiering logic as the frontend's existing `projectRiskStatus`) and `_scanners_used(by_kind) -> list[str]` (human labels for whichever of sast/secret/sca/config are non-zero in this scan — e.g. `"Secrets"`, `"Dependencies (SCA)"`).

### `scan_report_executive.html.j2` (new, ported from the CLI)

Adapted field-by-field from `zero-strike-cli/src/reporting/templates/report.html.j2` to this app's actual schema — not a literal copy:

| CLI template expects | Portal reality | Adaptation |
|---|---|---|
| `f.risk_score` / `f.cvss_score` | `f.priority_score`; no CVSS anywhere | use `f.priority_score`; CVSS row dropped (Jinja treats the missing attribute as `Undefined`/falsy, so the existing `{% if f.cvss_score %}` guard silently omits it — no template crash, no code change needed there) |
| `f.recommendation` | `f.remediation` | rename throughout |
| `f.file` / `f.line` | `f.location.file` / `f.location.start_line` | rename throughout |
| `f.code_snippet` | `f.evidence[0].snippet` | `f.evidence[0].snippet if f.evidence else None` |
| `f.scanner == 'gitleaks'` / `'osv-scanner'` (multi-engine assumption) | single scanner binary, differentiated by `f.kind` | secrets section keys off `f.kind == 'secret'`, dependency section off `f.kind == 'sca'`; "Scanner Coverage" table replaced with a "Findings by Kind" table from `report.stats.by_kind` (real, already-tracked data) |
| inline `owasp_all` list (A01-A10, CLI's own ordering) | `app.core.owasp.OWASP_TOP_10` (different ordering, canonical in this app) | template iterates the portal's own mapping, passed into the render context — no duplicate/contradictory OWASP list ships in this codebase |
| `result.overall_risk` | not tracked | computed for real via `_overall_risk()` above |
| `result.scanners_used` | not tracked as such | computed for real via `_scanners_used()` above |
| `result.executive_summary` (AI-written prose) | no AI provider configured anywhere in this app | replaced with a short deterministic sentence built from real stats, e.g. `"{total} findings across {files_scanned} files, {critical} critical."` — not AI-written, not invented |
| `result.tech_stack` | no tech-stack detection | kept as `None`; the CLI template already has a graceful fallback branch ("Technology stack detection was not performed") — reused as-is |
| `result.ai_provider` | none configured | kept in the layout per the decision below, rendered as `"Not tracked"` |

Per explicit decision: the tech-stack section and the "AI provider" line stay in the layout (not deleted) and render an honest placeholder, rather than being removed — consistent with this codebase's existing pattern of visibly saying "not available yet" rather than hiding a feature (see `notifyComingSoon` on the scan page).

## 3. Frontend: template picker + preview windows

New shared component `frontend/components/reports/report-template-picker.tsx`:
- Renders both templates side by side as small scaled `<iframe srcDoc={...}>` previews, sourced from `GET /report-templates/{template}/preview`.
- Takes `value`, `onChange`, and `allowInherit?: boolean`.
- Used in two places:
  - `Settings → Report Templates` (`frontend/app/(dashboard)/settings/report-templates/page.tsx`, replacing its "Coming soon" stub): `allowInherit=false`, edits the workspace default (admin-only mutation).
  - `Project Overview` tab (`frontend/app/(dashboard)/projects/[projectId]/page.tsx`, `OverviewTab`): `allowInherit=true` (Inherit / Standard / Executive), edits `project.report_template`.

## 4. Scan report page filters

Replace the current bespoke severity/kind toggle-button row + free-standing OWASP filter badge in `ScanDetailPage` with the existing `FilterBar` component, using `select`-type facets for all four axes: Severity, Kind, OWASP category (labeled via `OWASP_TITLES`), Priority (labeled via the new `lib/priority.ts`). The OWASP chart's existing click-to-filter behavior is preserved — it drives the same `owaspFilter` state the new dropdown also controls. No new UI component required; this is a rewire of an existing one.

Note: `FilterBar`'s `SelectFacet.value` is a required `string` (not `string | undefined`), so each of these four filters needs an explicit "All" sentinel value mapped to/from `undefined` when calling `listFindings` — the same sentinel pattern `ProjectOwaspSection` already uses (`ALL_REPOS = "__all__"`) for its repo-scope `Select`.

## Explicitly out of scope

- CVSS scoring — the scanner emits no CVSS data; not fabricated.
- Sorting findings by priority — only filtering was requested; trivial to add later.
- Backfilling `priority_score` on already-ingested findings — self-heals on next scan.
- Preview windows reflecting a real project's actual findings — uses fixture sample data instead, since the Settings page isn't project-scoped and this avoids exposing real data in a template picker.

## Files touched (implementation-phase reference)

**Backend (new)**: `app/core/priority.py`, `app/models/workspace_settings.py`, `app/routers/report_templates.py`, `app/services/report_template_service.py`, `app/reporting/templates/scan_report_executive.html.j2`

**Backend (modified)**: `app/models/finding.py`, `app/models/project.py`, `app/schemas/report.py`, `app/schemas/project.py`, `app/routers/scans.py`, `app/routers/projects.py`, `app/services/report_ingestion_service.py`, `app/services/pdf_report_service.py`, `app/main.py` (register new router)

**Frontend (new)**: `lib/priority.ts`, `components/reports/report-template-picker.tsx`

**Frontend (modified)**: `lib/api/findings.ts`, `lib/api/projects.ts`, `app/(dashboard)/settings/report-templates/page.tsx`, `app/(dashboard)/projects/[projectId]/page.tsx`, `app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx`

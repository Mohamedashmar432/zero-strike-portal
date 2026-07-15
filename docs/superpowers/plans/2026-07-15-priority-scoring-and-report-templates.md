# Priority Scoring, Executive Report Template & Enhanced Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deterministic 0-10 priority score to every finding, a second "Executive" PDF report template selectable per-project (with a workspace default), and dropdown-style severity/kind/OWASP/priority filters on the scan report page.

**Architecture:** One new pure scoring module (`app/core/priority.py`) feeds a new `Finding.priority_score`/`priority_tier` pair computed once at ingestion. A new `WorkspaceSettings` singleton + a `Project.report_template` override resolve which of two Jinja templates `pdf_report_service` renders. The scan-report page's ad-hoc filter buttons are replaced by the existing `FilterBar` component's dropdown facets.

**Tech Stack:** FastAPI + Beanie/Mongo (mongomock in tests) + Jinja2/xhtml2pdf on the backend; Next.js 16 + TanStack Query + shadcn/ui (`@base-ui/react`) on the frontend, no frontend test runner (verify via `npm run build` / `npm run lint`).

Full design rationale: `docs/superpowers/specs/2026-07-15-priority-scoring-and-report-templates-design.md`.

---

## File Structure

**Backend — new files:**
- `app/core/priority.py` — pure `compute_priority()` scoring function
- `app/models/workspace_settings.py` — singleton `WorkspaceSettings` document
- `app/services/report_template_service.py` — resolves effective template (project override → workspace default)
- `app/schemas/report_template.py` — request/response schemas for the settings endpoint
- `app/routers/report_templates.py` — `GET/PUT /report-templates/settings`, `GET /report-templates/{template}/preview`
- `app/reporting/sample_data.py` — fixture Scan/Report/Finding for the preview endpoint
- `app/reporting/templates/scan_report_executive.html.j2` — the ported/adapted CLI template

**Backend — modified files:**
- `app/models/finding.py` — `priority_score`, `priority_tier` fields
- `app/models/project.py` — `report_template` field
- `app/schemas/report.py` — `FindingResponse` gains priority fields
- `app/schemas/project.py` — `ProjectUpdateRequest`/`ProjectResponse` gain `report_template`
- `app/services/report_ingestion_service.py` — computes priority at ingestion
- `app/services/pdf_report_service.py` — template selection + executive-only context helpers
- `app/routers/scans.py` — `priority` filter on findings list; resolves effective template for PDF download
- `app/routers/projects.py` — `report_template` read/write
- `app/db/mongo.py` — registers `WorkspaceSettings` with Beanie
- `app/main.py` — registers `report_templates` router

**Frontend — new files:**
- `lib/priority.ts` — priority tier labels/order (mirrors `lib/owasp.ts`)
- `lib/api/report-templates.ts` — workspace settings + preview URL helper
- `components/reports/report-template-picker.tsx` — shared picker + preview UI

**Frontend — modified files:**
- `lib/api/findings.ts` — `priority_score`/`priority_tier` on `Finding`, `priority` filter param
- `lib/api/projects.ts` — `report_template` on `Project`, in `updateProject` patch
- `app/(dashboard)/settings/report-templates/page.tsx` — replaces "Coming soon" stub
- `app/(dashboard)/projects/[projectId]/page.tsx` — `OverviewTab` gets a Report Template card
- `app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx` — dropdown filters + real priority display

---

## Task 1: Priority scoring function

**Files:**
- Create: `backend/app/core/priority.py`
- Test: `backend/tests/test_priority.py`

- [ ] **Step 1: Write the failing test**

```python
from app.core.priority import compute_priority


def test_critical_severity_with_owasp_and_high_confidence_maxes_out():
    score, tier = compute_priority("critical", ["A03:2025"], "high")
    assert score == 10.0
    assert tier == "critical"


def test_high_severity_no_owasp_no_confidence_data_stays_high():
    score, tier = compute_priority("high", [], None)
    assert score == 6.0
    assert tier == "high"


def test_medium_severity_with_owasp_and_high_confidence_is_bumped_to_high_tier():
    score, tier = compute_priority("medium", ["A05:2025"], "high")
    assert score == 6.0
    assert tier == "high"


def test_high_severity_low_confidence_no_owasp_drops_to_medium_tier():
    score, tier = compute_priority("high", [], "low")
    assert score == 5.5
    assert tier == "medium"


def test_info_severity_with_owasp_and_high_confidence_never_leaves_low_tier():
    score, tier = compute_priority("info", ["A05:2025"], "high")
    assert score == 2.5
    assert tier == "low"


def test_unknown_severity_is_zero_baseline():
    score, tier = compute_priority(None, [], None)
    assert score == 0.0
    assert tier == "low"


def test_score_never_exceeds_ten():
    score, _ = compute_priority("critical", ["A01:2025", "A02:2025"], "high")
    assert score == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_priority.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.priority'`

- [ ] **Step 3: Write the implementation**

```python
"""Deterministic finding priority score — independent of severity, boosted by OWASP
Top-10 relevance and scanner confidence. See
docs/superpowers/specs/2026-07-15-priority-scoring-and-report-templates-design.md for
the rationale behind the weights and tier boundaries.
"""

from typing import Literal

PriorityTier = Literal["critical", "high", "medium", "low"]

_SEVERITY_BASE: dict[str, float] = {
    "critical": 8.0,
    "high": 6.0,
    "medium": 4.0,
    "low": 2.0,
    "info": 0.5,
}
_OWASP_BOOST = 1.5
_CONFIDENCE_ADJ: dict[str, float] = {"high": 0.5, "low": -0.5}


def compute_priority(
    severity: str | None, owasp: list[str], confidence: str | None
) -> tuple[float, PriorityTier]:
    score = _SEVERITY_BASE.get(severity or "", 0.0)
    if owasp:
        score += _OWASP_BOOST
    score += _CONFIDENCE_ADJ.get(confidence or "", 0.0)
    score = round(max(0.0, min(10.0, score)), 1)

    tier: PriorityTier
    if score >= 8.0:
        tier = "critical"
    elif score >= 6.0:
        tier = "high"
    elif score >= 4.0:
        tier = "medium"
    else:
        tier = "low"
    return score, tier
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_priority.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/priority.py backend/tests/test_priority.py
git commit -m "feat: add deterministic finding priority scoring"
```

---

## Task 2: Add priority fields to the Finding model

**Files:**
- Modify: `backend/app/models/finding.py:64-65`

- [ ] **Step 1: Add the fields**

In `backend/app/models/finding.py`, find:

```python
    severity: Literal["critical", "high", "medium", "low", "info"] | None = None
    confidence: str | None = None
```

Replace with:

```python
    severity: Literal["critical", "high", "medium", "low", "info"] | None = None
    confidence: str | None = None
    # Computed at ingestion time from severity + OWASP relevance + confidence — see
    # app.core.priority.compute_priority. None for findings ingested before this field
    # existed; self-heals on the next (re-)scan since ingestion always replaces findings.
    priority_score: float | None = None
    priority_tier: Literal["critical", "high", "medium", "low"] | None = None
```

- [ ] **Step 2: Verify the app still imports cleanly**

Run: `cd backend && ./.venv/Scripts/python -c "from app.models.finding import Finding"`
Expected: no output, exit code 0

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/finding.py
git commit -m "feat: add priority_score and priority_tier fields to Finding"
```

---

## Task 3: Wire priority scoring into ingestion

**Files:**
- Modify: `backend/app/services/report_ingestion_service.py:9-10`, `:64-83`
- Test: `backend/tests/test_report_ingestion.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_report_ingestion.py` (after `test_finding_field_mapping_by_kind`):

```python
def test_map_finding_computes_priority_score_and_tier():
    report = _load()
    by_kind = {f.kind: ingest_svc._map_finding("s1", "p1", f) for f in report.findings}

    sast = by_kind["sast"]  # critical, high confidence, OWASP-tagged
    assert sast.priority_score == 10.0
    assert sast.priority_tier == "critical"

    secret = by_kind["secret"]  # high, high confidence, no OWASP tag
    assert secret.priority_score == 6.5
    assert secret.priority_tier == "high"

    sca = by_kind["sca"]  # medium, high confidence, OWASP-tagged
    assert sca.priority_score == 6.0
    assert sca.priority_tier == "high"

    config = by_kind["config"]  # low, medium confidence, OWASP-tagged
    assert config.priority_score == 3.5
    assert config.priority_tier == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_report_ingestion.py::test_map_finding_computes_priority_score_and_tier -v`
Expected: FAIL — `AttributeError: 'Finding' object has no attribute 'priority_score'` is wrong (field exists from Task 2, will be `None`), actual failure: `assert None == 10.0`

- [ ] **Step 3: Wire it in**

In `backend/app/services/report_ingestion_service.py`, find:

```python
from app.core.owasp import OWASP_CODES_ORDERED
from app.models.finding import (
```

Replace with:

```python
from app.core.owasp import OWASP_CODES_ORDERED
from app.core.priority import compute_priority
from app.models.finding import (
```

Then find:

```python
def _map_finding(
    scan_id: str,
    project_id: str,
    f: GoFindingIn,
    project_repo_id: str | None = None,
    root_path: str | None = None,
) -> Finding:
    return Finding(
        scan_id=scan_id,
        project_id=project_id,
        project_repo_id=project_repo_id,
        finding_id=f.finding_id,
        fingerprint=f.fingerprint,
        rule_id=f.rule_id,
        rule_name=f.rule_name,
        category=f.category,
        severity=f.severity if f.severity in _SEVERITIES else None,
        confidence=f.confidence,
        message=f.message or f.rule_name or "(no message)",
```

Replace with:

```python
def _map_finding(
    scan_id: str,
    project_id: str,
    f: GoFindingIn,
    project_repo_id: str | None = None,
    root_path: str | None = None,
) -> Finding:
    severity = f.severity if f.severity in _SEVERITIES else None
    priority_score, priority_tier = compute_priority(severity, f.owasp, f.confidence)
    return Finding(
        scan_id=scan_id,
        project_id=project_id,
        project_repo_id=project_repo_id,
        finding_id=f.finding_id,
        fingerprint=f.fingerprint,
        rule_id=f.rule_id,
        rule_name=f.rule_name,
        category=f.category,
        severity=severity,
        confidence=f.confidence,
        priority_score=priority_score,
        priority_tier=priority_tier,
        message=f.message or f.rule_name or "(no message)",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_report_ingestion.py -v`
Expected: all tests in the file pass (including the new one)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/report_ingestion_service.py backend/tests/test_report_ingestion.py
git commit -m "feat: compute priority score/tier for every finding at ingestion"
```

---

## Task 4: Expose priority on the findings API + filter param

**Files:**
- Modify: `backend/app/schemas/report.py:180-181`
- Modify: `backend/app/routers/scans.py:38`, `:226-242`
- Test: `backend/tests/test_scans.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_scans.py` (after `test_scan_report_and_findings_readable`):

```python
def test_findings_expose_and_filter_by_priority(client):
    owner = register_and_login(client, email="sowner12@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    scan_id = _scanner_scan(client, _headers(owner), project["id"], upload=True)

    findings = client.get(f"/api/v1/scans/{scan_id}/findings", headers=_headers(owner)).json()
    by_rule = {f["rule_id"]: f for f in findings["items"]}
    assert by_rule["ZS-PY-001"]["priority_score"] == 10.0
    assert by_rule["ZS-PY-001"]["priority_tier"] == "critical"

    critical_priority = client.get(
        f"/api/v1/scans/{scan_id}/findings?priority=critical", headers=_headers(owner)
    ).json()
    assert critical_priority["total"] == 1
    assert critical_priority["items"][0]["rule_id"] == "ZS-PY-001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_scans.py::test_findings_expose_and_filter_by_priority -v`
Expected: FAIL — `KeyError: 'priority_score'`

- [ ] **Step 3: Add the response fields**

In `backend/app/schemas/report.py`, find:

```python
    severity: str | None
    confidence: str | None
```

(inside `FindingResponse`) Replace with:

```python
    severity: str | None
    confidence: str | None
    priority_score: float | None
    priority_tier: str | None
```

- [ ] **Step 4: Populate the response and add the query filter**

In `backend/app/routers/scans.py`, find:

```python
        severity=f.severity,
        confidence=f.confidence,
        message=f.message,
```

Replace with:

```python
        severity=f.severity,
        confidence=f.confidence,
        priority_score=f.priority_score,
        priority_tier=f.priority_tier,
        message=f.message,
```

Then find:

```python
@router.get("/scans/{scan_id}/findings", response_model=Page)
async def list_scan_findings(
    scan_id: str,
    severity: str | None = Query(None),
    kind: str | None = Query(None),
    owasp: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)

    criteria = [Finding.scan_id == scan_id]
    if severity:
        criteria.append(Finding.severity == severity)
    if kind:
        criteria.append(Finding.kind == kind)
    if owasp:
        criteria.append(Finding.owasp == owasp)
```

Replace with:

```python
@router.get("/scans/{scan_id}/findings", response_model=Page)
async def list_scan_findings(
    scan_id: str,
    severity: str | None = Query(None),
    kind: str | None = Query(None),
    owasp: str | None = Query(None),
    priority: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)

    criteria = [Finding.scan_id == scan_id]
    if severity:
        criteria.append(Finding.severity == severity)
    if kind:
        criteria.append(Finding.kind == kind)
    if owasp:
        criteria.append(Finding.owasp == owasp)
    if priority:
        criteria.append(Finding.priority_tier == priority)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_scans.py tests/test_report_ingestion.py -v`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/report.py backend/app/routers/scans.py backend/tests/test_scans.py
git commit -m "feat: expose priority_score/tier on findings API, add priority filter"
```

---

## Task 5: Workspace settings singleton + report template resolution service

**Files:**
- Create: `backend/app/models/workspace_settings.py`
- Create: `backend/app/services/report_template_service.py`
- Modify: `backend/app/db/mongo.py`
- Test: `backend/tests/test_report_template_service.py`

- [ ] **Step 1: Write the failing test**

```python
import asyncio
from datetime import datetime, timezone

from app.models.project import Project
from app.services import report_template_service


def test_get_workspace_settings_creates_default_singleton_on_first_read(client):
    async def run():
        settings = await report_template_service.get_workspace_settings()
        assert settings.default_report_template == "standard"
        again = await report_template_service.get_workspace_settings()
        assert str(again.id) == str(settings.id)

    asyncio.run(run())


def test_set_default_report_template_persists(client):
    async def run():
        await report_template_service.set_default_report_template("executive")
        settings = await report_template_service.get_workspace_settings()
        assert settings.default_report_template == "executive"

    asyncio.run(run())


def test_effective_template_prefers_project_override(client):
    async def run():
        now = datetime.now(timezone.utc)
        project = Project(
            name="p", owner_id="u1", created_at=now, updated_at=now, report_template="executive"
        )
        await project.insert()
        await report_template_service.set_default_report_template("standard")

        assert await report_template_service.get_effective_template(project) == "executive"

    asyncio.run(run())


def test_effective_template_falls_back_to_workspace_default(client):
    async def run():
        now = datetime.now(timezone.utc)
        project = Project(name="p2", owner_id="u1", created_at=now, updated_at=now)
        await project.insert()
        await report_template_service.set_default_report_template("executive")

        assert await report_template_service.get_effective_template(project) == "executive"

    asyncio.run(run())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_report_template_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.report_template_service'`

- [ ] **Step 3: Create the WorkspaceSettings model**

```python
from typing import Literal

from beanie import Document

ReportTemplate = Literal["standard", "executive"]


class WorkspaceSettings(Document):
    """Singleton — at most one document ever exists (see report_template_service,
    which creates it lazily on first read). Workspace-wide preferences that apply to
    every project unless a project sets its own override (see Project.report_template).
    """

    default_report_template: ReportTemplate = "standard"

    class Settings:
        name = "workspace_settings"
```

- [ ] **Step 4: Register it with Beanie**

In `backend/app/db/mongo.py`, find:

```python
from app.models.user import User
```

Replace with:

```python
from app.models.user import User
from app.models.workspace_settings import WorkspaceSettings
```

Then find:

```python
            RepoCredential,
            ProjectRepo,
        ],
```

Replace with:

```python
            RepoCredential,
            ProjectRepo,
            WorkspaceSettings,
        ],
```

- [ ] **Step 5: Create the resolution service**

```python
"""Resolves which PDF report template applies: a project's own override, falling back
to the single workspace-wide default. See WorkspaceSettings — at most one document
ever exists, created lazily on first read.
"""

from app.models.project import Project
from app.models.workspace_settings import ReportTemplate, WorkspaceSettings


async def get_workspace_settings() -> WorkspaceSettings:
    settings = await WorkspaceSettings.find_one()
    if settings is None:
        settings = WorkspaceSettings()
        await settings.insert()
    return settings


async def set_default_report_template(template: ReportTemplate) -> WorkspaceSettings:
    settings = await get_workspace_settings()
    settings.default_report_template = template
    await settings.save()
    return settings


async def get_effective_template(project: Project) -> ReportTemplate:
    if project.report_template is not None:
        return project.report_template
    settings = await get_workspace_settings()
    return settings.default_report_template
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_report_template_service.py -v`
Expected: 4 passed

(Note: `test_effective_template_prefers_project_override` needs `Project.report_template` to exist — that field is added in Task 6. If this task is done before Task 6, add a throwaway `report_template: str | None = None` stub to `Project` first, or simply do Task 6 first. **Do Task 6 before running this test file** if working strictly in order — the two tasks are commutable but the test imports `Project(..., report_template=...)`.)

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/workspace_settings.py backend/app/services/report_template_service.py backend/app/db/mongo.py backend/tests/test_report_template_service.py
git commit -m "feat: add workspace settings singleton and report template resolution"
```

---

## Task 6: Project-level report template override

**Files:**
- Modify: `backend/app/models/project.py`
- Modify: `backend/app/schemas/project.py:15-18`, `:57-67`
- Modify: `backend/app/routers/projects.py:34-53`, `:152-169`
- Test: `backend/tests/test_projects.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_projects.py`:

```python
def test_owner_can_set_and_clear_report_template_override(client):
    owner = register_and_login(client, email="owner7@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    assert project["report_template"] is None

    r = client.patch(
        f"/api/v1/projects/{project['id']}", json={"report_template": "executive"}, headers=_headers(owner)
    )
    assert r.status_code == 200
    assert r.json()["report_template"] == "executive"

    r = client.patch(
        f"/api/v1/projects/{project['id']}", json={"report_template": "inherit"}, headers=_headers(owner)
    )
    assert r.status_code == 200
    assert r.json()["report_template"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_projects.py::test_owner_can_set_and_clear_report_template_override -v`
Expected: FAIL — `assert 'report_template' in {...}` style KeyError, or `TypeError` on `project["report_template"]` being absent

- [ ] **Step 3: Add the field to the Project model**

In `backend/app/models/project.py`, find:

```python
from datetime import datetime

from beanie import Document, Indexed


class Project(Document):
    name: Indexed(str)  # type: ignore[valid-type]
    description: str | None = None
    owner_id: Indexed(str)  # type: ignore[valid-type]
    is_archived: bool = False
    scan_count: int = 0
    last_scan_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
```

Replace with:

```python
from datetime import datetime
from typing import Literal

from beanie import Document, Indexed


class Project(Document):
    name: Indexed(str)  # type: ignore[valid-type]
    description: str | None = None
    owner_id: Indexed(str)  # type: ignore[valid-type]
    is_archived: bool = False
    scan_count: int = 0
    last_scan_at: datetime | None = None
    # None = inherit the workspace-wide default (see report_template_service).
    report_template: Literal["standard", "executive"] | None = None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Add the field to the schemas**

In `backend/app/schemas/project.py`, find:

```python
class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_archived: bool | None = None
```

Replace with:

```python
class ProjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    is_archived: bool | None = None
    # "inherit" clears the override (stored as None); None here means "not provided in
    # this patch", distinguishing "don't touch" from "explicitly clear."
    report_template: Literal["inherit", "standard", "executive"] | None = None
```

Then find (in `ProjectResponse`):

```python
    scan_count: int
    last_scan_at: datetime | None
    created_at: datetime
    updated_at: datetime
    my_role: Literal["owner", "collaborator", "admin"]
```

Replace with:

```python
    scan_count: int
    last_scan_at: datetime | None
    report_template: Literal["standard", "executive"] | None
    created_at: datetime
    updated_at: datetime
    my_role: Literal["owner", "collaborator", "admin"]
```

- [ ] **Step 5: Wire the router**

In `backend/app/routers/projects.py`, find:

```python
        scan_count=project.scan_count,
        last_scan_at=project.last_scan_at,
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=my_role,
```

Replace with:

```python
        scan_count=project.scan_count,
        last_scan_at=project.last_scan_at,
        report_template=project.report_template,
        created_at=project.created_at,
        updated_at=project.updated_at,
        my_role=my_role,
```

Then find:

```python
    if payload.is_archived is not None:
        project.is_archived = payload.is_archived
    project.updated_at = datetime.now(timezone.utc)
```

Replace with:

```python
    if payload.is_archived is not None:
        project.is_archived = payload.is_archived
    if payload.report_template is not None:
        project.report_template = None if payload.report_template == "inherit" else payload.report_template
    project.updated_at = datetime.now(timezone.utc)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_projects.py tests/test_report_template_service.py -v`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/app/models/project.py backend/app/schemas/project.py backend/app/routers/projects.py backend/tests/test_projects.py
git commit -m "feat: let a project override the workspace default report template"
```

---

## Task 7: pdf_report_service — template selection + executive-only helpers

**Files:**
- Modify: `backend/app/services/pdf_report_service.py` (full rewrite of the render logic)
- Test: `backend/tests/test_pdf_report.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_pdf_report.py` (add `import asyncio` to the top-of-file imports first):

```python
def test_render_scan_report_html_standard_is_unaffected_by_the_new_param(client):
    async def run():
        from app.models.finding import Finding
        from app.models.report import Report
        from app.models.scan import Scan
        from app.services import pdf_report_service

        owner_tokens = register_and_login(client, email="pdfowner5@zerostrike.dev")
        project = _create_project(client, _headers(owner_tokens))
        scan_id = _create_scan(
            client, _headers(owner_tokens), project["id"], report_bytes=_FIXTURE.read_bytes()
        )
        scan = await Scan.get(scan_id)
        report = await Report.find_one(Report.scan_id == scan_id)
        findings = await Finding.find(Finding.scan_id == scan_id).to_list()

        html = pdf_report_service.render_scan_report_html(scan, report, findings, "standard")
        assert "ZeroStrike Scan Report" in html

    asyncio.run(run())


def test_render_scan_report_html_executive_includes_overall_risk_and_canonical_owasp_titles(client):
    async def run():
        from app.models.finding import Finding
        from app.models.report import Report
        from app.models.scan import Scan
        from app.services import pdf_report_service

        owner_tokens = register_and_login(client, email="pdfowner6@zerostrike.dev")
        project = _create_project(client, _headers(owner_tokens))
        scan_id = _create_scan(
            client, _headers(owner_tokens), project["id"], report_bytes=_FIXTURE.read_bytes()
        )
        scan = await Scan.get(scan_id)
        report = await Report.find_one(Report.scan_id == scan_id)
        findings = await Finding.find(Finding.scan_id == scan_id).to_list()

        html = pdf_report_service.render_scan_report_html(
            scan, report, findings, "executive", project_name="Demo"
        )
        assert "Overall Risk: CRITICAL" in html
        # The portal's own canonical OWASP_TOP_10 titles must appear (not the CLI's
        # stale/differently-ordered inline list).
        assert "Broken Access Control" in html
        assert "10.0/10" in html  # the SQLi finding's priority score, from the fixture

    asyncio.run(run())


def test_scan_report_pdf_uses_executive_template_when_project_overrides(client):
    owner = register_and_login(client, email="pdfowner7@zerostrike.dev")
    project = _create_project(client, _headers(owner))
    client.patch(
        f"/api/v1/projects/{project['id']}", json={"report_template": "executive"}, headers=_headers(owner)
    )
    scan_id = _create_scan(client, _headers(owner), project["id"], report_bytes=_FIXTURE.read_bytes())

    r = client.get(f"/api/v1/scans/{scan_id}/report/pdf", headers=_headers(owner))
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_pdf_report.py -v`
Expected: FAIL — `AttributeError: module 'app.services.pdf_report_service' has no attribute 'render_scan_report_html'`

- [ ] **Step 3: Rewrite `pdf_report_service.py`**

Replace the entire contents of `backend/app/services/pdf_report_service.py` with:

```python
"""Renders a completed scan's report + findings to PDF.

Two templates: "standard" (scan_report.html.j2, the original plain layout) and
"executive" (scan_report_executive.html.j2, ported from zero-strike-cli's branded
report). See docs/superpowers/specs/2026-07-15-priority-scoring-and-report-templates-design.md.

xhtml2pdf (not WeasyPrint) is the renderer: it's pure Python with no native
Pango/GObject runtime to install, so the same code works unmodified in the Linux
Docker image and on a bare Windows dev machine.
"""

import asyncio
import io
from pathlib import Path
from typing import Literal

from jinja2 import Environment, FileSystemLoader, select_autoescape
from xhtml2pdf import pisa

from app.core.owasp import OWASP_TOP_10
from app.models.finding import Finding
from app.models.report import Report
from app.models.scan import Scan

ReportTemplate = Literal["standard", "executive"]

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_MAX_FINDINGS = 2000
_TEMPLATE_FILES: dict[ReportTemplate, str] = {
    "standard": "scan_report.html.j2",
    "executive": "scan_report_executive.html.j2",
}
_KIND_LABELS = {
    "sast": "Static Analysis (SAST)",
    "secret": "Secrets",
    "sca": "Dependencies (SCA)",
    "config": "Configuration",
}

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent.parent / "reporting" / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)


def _severity_sort_key(finding: Finding) -> tuple[int, str]:
    return (_SEVERITY_ORDER.get(finding.severity, len(_SEVERITY_ORDER)), finding.rule_id or "")


def _overall_risk(by_severity: dict[str, int]) -> str:
    if by_severity.get("critical"):
        return "CRITICAL"
    if by_severity.get("high"):
        return "HIGH"
    if by_severity.get("medium"):
        return "MEDIUM"
    if by_severity.get("low"):
        return "LOW"
    return "NONE"


def _scanners_used(by_kind: dict[str, int]) -> list[str]:
    return [_KIND_LABELS[kind] for kind in ("sast", "secret", "sca", "config") if by_kind.get(kind)]


def _executive_summary(report: Report, total_findings: int) -> str:
    critical = report.stats.by_severity.get("critical", 0)
    files = report.stats.files_scanned
    files_part = f" across {files} file{'s' if files != 1 else ''}" if files is not None else ""
    critical_part = f", {critical} critical" if critical else ""
    return f"{total_findings} finding{'s' if total_findings != 1 else ''}{files_part}{critical_part}."


_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _cwe_summary(findings: list[Finding]) -> list[dict]:
    by_cwe: dict[str, list[Finding]] = {}
    for f in findings:
        for cwe in f.cwe:
            by_cwe.setdefault(cwe, []).append(f)
    summary = []
    for cwe, items in by_cwe.items():
        max_severity = min(items, key=lambda f: _SEVERITY_RANK.get(f.severity, 5)).severity
        summary.append({"cwe": cwe, "count": len(items), "max_severity": max_severity})
    return summary


def render_scan_report_html(
    scan: Scan,
    report: Report,
    findings: list[Finding],
    template: ReportTemplate = "standard",
    project_name: str | None = None,
) -> str:
    ordered = sorted(findings, key=_severity_sort_key)
    limited = ordered[:_MAX_FINDINGS]
    jinja_template = _env.get_template(_TEMPLATE_FILES[template])
    context: dict = {
        "scan": scan,
        "report": report,
        "findings": limited,
        "total_findings": len(findings),
        "truncated": len(findings) > _MAX_FINDINGS,
    }
    if template == "executive":
        context.update(
            project_name=project_name or "—",
            owasp_all=list(OWASP_TOP_10.items()),
            overall_risk=_overall_risk(report.stats.by_severity),
            scanners_used=_scanners_used(report.stats.by_kind),
            executive_summary=_executive_summary(report, len(findings)),
            cwe_summary=_cwe_summary(findings),
        )
    return jinja_template.render(**context)


def _html_to_pdf_sync(html: str) -> bytes:
    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf)
    if result.err:
        raise RuntimeError(f"PDF rendering failed ({result.err} error(s))")
    return buf.getvalue()


async def render_scan_report_pdf(
    scan: Scan,
    report: Report,
    findings: list[Finding],
    template: ReportTemplate = "standard",
    project_name: str | None = None,
) -> bytes:
    html = render_scan_report_html(scan, report, findings, template, project_name)
    return await asyncio.to_thread(_html_to_pdf_sync, html)
```

- [ ] **Step 4: Update the PDF download route to resolve the effective template**

In `backend/app/routers/scans.py`, find:

```python
from app.services import (
    audit_service,
    connection_service,
    pdf_report_service,
    project_repo_service,
    project_service,
    scan_queue_service,
    scan_service,
)
```

Replace with:

```python
from app.services import (
    audit_service,
    connection_service,
    pdf_report_service,
    project_repo_service,
    project_service,
    report_template_service,
    scan_queue_service,
    scan_service,
)
```

Then find:

```python
@router.get("/scans/{scan_id}/report/pdf")
async def get_scan_report_pdf(scan_id: str, user: User = Depends(get_current_user)):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    report = await Report.find_one(Report.scan_id == scan_id)
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No report for this scan yet")

    findings = await Finding.find(Finding.scan_id == scan_id).to_list()
    pdf_bytes = await pdf_report_service.render_scan_report_pdf(scan, report, findings)
```

Replace with:

```python
@router.get("/scans/{scan_id}/report/pdf")
async def get_scan_report_pdf(scan_id: str, user: User = Depends(get_current_user)):
    scan = await scan_service.get_scan_or_404(scan_id)
    await project_service.require_member(scan.project_id, user)
    report = await Report.find_one(Report.scan_id == scan_id)
    if not report:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No report for this scan yet")

    project = await project_service.get_project_or_404(scan.project_id)
    template = await report_template_service.get_effective_template(project)
    findings = await Finding.find(Finding.scan_id == scan_id).to_list()
    pdf_bytes = await pdf_report_service.render_scan_report_pdf(scan, report, findings, template, project.name)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_pdf_report.py -v`
Expected: FAIL still, at this point, on the two new "executive" tests — the template file (`scan_report_executive.html.j2`) doesn't exist yet. That's expected; it's created in Task 8. Confirm instead that the pre-existing 4 tests plus `test_render_scan_report_html_standard_is_unaffected_by_the_new_param` pass:

Run: `cd backend && ./.venv/Scripts/pytest tests/test_pdf_report.py -k "not executive" -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pdf_report_service.py backend/app/routers/scans.py backend/tests/test_pdf_report.py
git commit -m "feat: support selectable PDF report templates in pdf_report_service"
```

---

## Task 8: The ported "Executive" Jinja template

**Files:**
- Create: `backend/app/reporting/templates/scan_report_executive.html.j2`
- Test: `backend/tests/test_pdf_report.py` (already written in Task 7 — this task makes those two tests pass)

- [ ] **Step 1: Create the template**

```jinja
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 13px; color: #1a1a2e; background: #fff; }

.cover {
  page-break-after: always;
  background: linear-gradient(150deg, #0d1b2a 0%, #1b2838 50%, #0f3460 100%);
  color: #fff;
  min-height: 100vh;
  padding: 72px 64px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.cover-eyebrow { font-size: 11px; letter-spacing: 3px; text-transform: uppercase; color: #7ec8e3; margin-bottom: 12px; }
.cover-title { font-size: 44px; font-weight: 800; letter-spacing: -1.5px; line-height: 1.1; margin-bottom: 8px; }
.cover-subtitle { font-size: 16px; color: #a8dadc; font-weight: 400; margin-bottom: 48px; }

.cover-meta { display: grid; grid-template-columns: 1fr 1fr; gap: 20px 40px; margin-bottom: 40px; }
.meta-item label { font-size: 10px; text-transform: uppercase; letter-spacing: 1.5px; color: #7ec8e3; display: block; margin-bottom: 4px; }
.meta-item span { font-size: 15px; font-weight: 600; }

.cover-stats { display: grid; grid-template-columns: repeat(6, 1fr); gap: 10px; margin-bottom: 40px; }
.stat-box { background: rgba(255,255,255,0.07); border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 14px 10px; text-align: center; }
.stat-box .num { font-size: 28px; font-weight: 800; display: block; }
.stat-box .lbl { font-size: 9px; text-transform: uppercase; letter-spacing: 1px; color: #a8dadc; margin-top: 4px; display: block; }
.stat-total .num { color: #fff; }
.stat-crit .num  { color: #ff4d6d; }
.stat-high .num  { color: #ff9a3c; }
.stat-med .num   { color: #ffd166; }
.stat-low .num   { color: #06d6a0; }
.stat-info .num  { color: #8ab4ff; }

.risk-banner { display: inline-flex; align-items: center; gap: 12px; padding: 12px 24px; border-radius: 6px; font-weight: 700; font-size: 14px; }
.risk-CRITICAL { background: #e63946; color: #fff; }
.risk-HIGH     { background: #f4a261; color: #1a1a2e; }
.risk-MEDIUM   { background: #e9c46a; color: #1a1a2e; }
.risk-LOW      { background: #2a9d8f; color: #fff; }
.risk-NONE     { background: #2a9d8f; color: #fff; }

.page { padding: 48px 56px; }
.page-break { page-break-before: always; }

h2 { font-size: 20px; font-weight: 700; color: #0f3460; border-bottom: 3px solid #e63946; padding-bottom: 8px; margin-bottom: 20px; margin-top: 40px; }
h3 { font-size: 14px; font-weight: 700; color: #16213e; margin-bottom: 8px; margin-top: 20px; }
p  { line-height: 1.7; margin-bottom: 10px; color: #333; }

.summary-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 28px; }
.summary-card { border-radius: 8px; padding: 16px 10px; text-align: center; }
.summary-card .count { font-size: 30px; font-weight: 800; display: block; }
.summary-card .label { font-size: 10px; text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; display: block; }
.card-critical { background: #fde8ea; color: #e63946; }
.card-high     { background: #fdf0e4; color: #e76f51; }
.card-medium   { background: #fdf8e4; color: #e9a825; }
.card-low      { background: #e4f5f3; color: #2a9d8f; }
.card-info     { background: #eef2ff; color: #6366f1; }

table { width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 12px; }
th { background: #0f3460; color: #fff; padding: 9px 12px; text-align: left; font-weight: 600; }
td { padding: 8px 12px; border-bottom: 1px solid #e8e8e8; vertical-align: top; }
tr:nth-child(even) td { background: #f8f9fa; }

.badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; }
.badge-CRITICAL { background: #fde8ea; color: #e63946; }
.badge-HIGH     { background: #fdf0e4; color: #e76f51; }
.badge-MEDIUM   { background: #fdf8e4; color: #e9a825; }
.badge-LOW      { background: #e4f5f3; color: #2a9d8f; }
.badge-INFO     { background: #eef2ff; color: #6366f1; }
.pass-badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; background: #e4f5f3; color: #2a9d8f; }
.fail-badge { display: inline-block; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 700; background: #fde8ea; color: #e63946; }

.finding-card { border: 1px solid #e8e8e8; border-radius: 8px; padding: 20px; margin-bottom: 16px; page-break-inside: avoid; }
.finding-card.sev-CRITICAL { border-left: 4px solid #e63946; }
.finding-card.sev-HIGH     { border-left: 4px solid #e76f51; }
.finding-card.sev-MEDIUM   { border-left: 4px solid #e9a825; }
.finding-card.sev-LOW      { border-left: 4px solid #2a9d8f; }
.finding-card.sev-INFO     { border-left: 4px solid #6366f1; }
.finding-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 10px; }
.finding-title  { font-weight: 700; font-size: 14px; color: #1a1a2e; flex: 1; margin-right: 12px; }
.finding-meta   { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; font-size: 12px; margin-bottom: 10px; }
.finding-meta span   { color: #666; }
.finding-meta strong { color: #1a1a2e; }
.finding-loc { grid-column: 1 / -1; font-family: 'Courier New', monospace; font-size: 11px; background: #f0f4ff; padding: 4px 8px; border-radius: 4px; color: #2c3e6b; }
.rec { background: #f0f7ff; border-left: 3px solid #0f3460; padding: 10px 14px; border-radius: 0 6px 6px 0; font-size: 12px; line-height: 1.6; color: #333; margin-top: 10px; }
pre.code-block { background: #0d1b2a; color: #e2e8f0; font-family: 'Courier New', monospace; font-size: 11px; line-height: 1.6; padding: 14px 16px; border-radius: 6px; overflow-x: auto; margin-top: 10px; white-space: pre-wrap; word-break: break-all; }

.owasp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 28px; }
.owasp-card { border: 1px solid #e8e8e8; border-radius: 8px; padding: 14px 16px; display: flex; justify-content: space-between; align-items: center; }
.owasp-card.fail-card { border-left: 4px solid #e63946; background: #fff8f8; }
.owasp-card.pass-card { border-left: 4px solid #2a9d8f; background: #f8fffd; }
.owasp-name { font-weight: 700; font-size: 12px; color: #1a1a2e; }
.owasp-code { font-size: 11px; color: #666; margin-top: 2px; }
.owasp-right { text-align: right; }
.owasp-count { font-size: 13px; font-weight: 700; color: #e63946; }

.conclusion { background: linear-gradient(135deg, #1a1a2e, #0f3460); color: #fff; border-radius: 10px; padding: 28px 32px; margin-top: 32px; }
.conclusion p { color: #a8dadc; margin-bottom: 8px; }

@page { margin: 0; size: A4; }
@media print {
  .cover                { min-height: 297mm; page-break-after: always; }
  .page-break           { page-break-before: always; }
  .finding-card         { page-break-inside: avoid; }
  pre.code-block        { page-break-inside: avoid; white-space: pre-wrap; word-break: break-all; overflow-wrap: break-word; max-width: 100%; }
  h2                    { page-break-after: avoid; }
  h3                    { page-break-after: avoid; }
  .owasp-grid           { display: block; }
  .owasp-card           { display: flex; page-break-inside: avoid; margin-bottom: 8px; }
  td, th                { word-break: break-word; overflow-wrap: break-word; }
  table                 { table-layout: fixed; width: 100%; }
  .finding-meta         { display: block; }
  .finding-meta > div   { margin-bottom: 3px; }
  .finding-loc          { display: block; margin-top: 4px; word-break: break-all; }
  .cover-stats          { grid-template-columns: repeat(6, 1fr); gap: 6px; }
  .stat-box             { padding: 10px 6px; }
  .stat-box .num        { font-size: 22px; }
  .summary-grid         { grid-template-columns: repeat(5, 1fr); }
  .conclusion           { page-break-inside: avoid; }
}
</style>
</head>
<body>

<div class="cover">
  <div>
    <div class="cover-eyebrow">ZeroStrike Security Assessment Report</div>
    <div class="cover-title">Security<br>Assessment</div>
    <div class="cover-subtitle">Static Application Security Testing</div>

    <div class="cover-meta">
      <div class="meta-item"><label>Project</label><span>{{ project_name }}</span></div>
      <div class="meta-item"><label>Repository</label><span>{{ scan.repo_url or report.root_path or "—" }}</span></div>
      <div class="meta-item"><label>Branch</label><span>{{ report.branch or scan.branch or "—" }}</span></div>
      <div class="meta-item"><label>Scan Date</label><span>{{ report.started_at.strftime('%Y-%m-%d') if report.started_at else "—" }}</span></div>
      <div class="meta-item"><label>AI Provider</label><span>Not tracked</span></div>
      <div class="meta-item"><label>Scan ID</label><span style="font-size:11px;font-family:monospace;">{{ (scan.id | string)[:8] }}</span></div>
    </div>

    <div class="cover-scanners">
      <label style="font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#7ec8e3;display:block;margin-bottom:10px;">Scanners Executed</label>
      {% for s in scanners_used %}
      <span class="scanner-pill" style="display:inline-block;background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:20px;padding:5px 14px;font-size:12px;margin-right:8px;margin-bottom:6px;">{{ s }}</span>
      {% endfor %}
    </div>

    <div class="cover-stats">
      <div class="stat-box stat-total"><span class="num">{{ total_findings }}</span><span class="lbl">Total</span></div>
      <div class="stat-box stat-crit"><span class="num">{{ report.stats.by_severity.get('critical', 0) }}</span><span class="lbl">Critical</span></div>
      <div class="stat-box stat-high"><span class="num">{{ report.stats.by_severity.get('high', 0) }}</span><span class="lbl">High</span></div>
      <div class="stat-box stat-med"><span class="num">{{ report.stats.by_severity.get('medium', 0) }}</span><span class="lbl">Medium</span></div>
      <div class="stat-box stat-low"><span class="num">{{ report.stats.by_severity.get('low', 0) }}</span><span class="lbl">Low</span></div>
      <div class="stat-box stat-info"><span class="num">{{ report.stats.by_severity.get('info', 0) }}</span><span class="lbl">Info</span></div>
    </div>
  </div>

  <div class="risk-banner risk-{{ overall_risk }}">
    Overall Risk: {{ overall_risk }}
  </div>
</div>

<div class="page page-break">

<h2>1. Executive Summary</h2>
<p>{{ executive_summary }}</p>

<div class="summary-grid">
  <div class="summary-card card-critical"><span class="count">{{ report.stats.by_severity.get('critical', 0) }}</span><span class="label">Critical</span></div>
  <div class="summary-card card-high"><span class="count">{{ report.stats.by_severity.get('high', 0) }}</span><span class="label">High</span></div>
  <div class="summary-card card-medium"><span class="count">{{ report.stats.by_severity.get('medium', 0) }}</span><span class="label">Medium</span></div>
  <div class="summary-card card-low"><span class="count">{{ report.stats.by_severity.get('low', 0) }}</span><span class="label">Low</span></div>
  <div class="summary-card card-info"><span class="count">{{ report.stats.by_severity.get('info', 0) }}</span><span class="label">Info</span></div>
</div>

<h2>2. Technology Stack</h2>
<p>Technology stack detection was not performed.</p>

<h2>3. Findings by Kind</h2>
<table>
  <tr><th>Kind</th><th>Findings</th></tr>
  {% for kind, label in [('sast','Static Analysis (SAST)'), ('secret','Secrets'), ('sca','Dependencies (SCA)'), ('config','Configuration')] %}
  {% if report.stats.by_kind.get(kind) %}
  <tr><td><strong>{{ label }}</strong></td><td>{{ report.stats.by_kind.get(kind) }}</td></tr>
  {% endif %}
  {% endfor %}
</table>

</div>

<div class="page page-break">

<h2>4. OWASP Top 10 Compliance</h2>

{% set ns = namespace(total_fail=0) %}
<div class="owasp-grid">
{% for code, name in owasp_all %}
  {% set cat_findings = [] %}
  {% for f in findings %}
    {% if f.owasp and code in f.owasp %}
      {% set _ = cat_findings.append(f) %}
    {% endif %}
  {% endfor %}
  {% set fail = cat_findings | length > 0 %}
  {% if fail %}{% set ns.total_fail = ns.total_fail + 1 %}{% endif %}
  <div class="owasp-card {{ 'fail-card' if fail else 'pass-card' }}">
    <div>
      <div class="owasp-name">{{ name }}</div>
      <div class="owasp-code">{{ code }}</div>
    </div>
    <div class="owasp-right">
      {% if fail %}
        <div><span class="fail-badge">FAIL</span></div>
        <div class="owasp-count">{{ cat_findings | length }} finding{{ 's' if cat_findings | length != 1 else '' }}</div>
        {% set sevs = cat_findings | map(attribute='severity') | list %}
        {% if 'critical' in sevs %}<div style="margin-top:4px;"><span class="badge badge-CRITICAL">CRITICAL</span></div>
        {% elif 'high' in sevs %}<div style="margin-top:4px;"><span class="badge badge-HIGH">HIGH</span></div>
        {% elif 'medium' in sevs %}<div style="margin-top:4px;"><span class="badge badge-MEDIUM">MEDIUM</span></div>
        {% else %}<div style="margin-top:4px;"><span class="badge badge-LOW">LOW</span></div>{% endif %}
      {% else %}
        <div><span class="pass-badge">PASS</span></div>
        <div style="font-size:11px;color:#2a9d8f;margin-top:4px;">No findings</div>
      {% endif %}
    </div>
  </div>
{% endfor %}
</div>

<p style="margin-top:12px;color:#333;">
  <strong>OWASP Summary:</strong>
  {{ ns.total_fail }} of 10 categories have findings.
  {% if ns.total_fail == 0 %}No OWASP Top 10 violations detected.
  {% elif ns.total_fail <= 3 %}Low OWASP exposure — address findings by priority.
  {% elif ns.total_fail <= 6 %}Moderate OWASP exposure — security review recommended.
  {% else %}High OWASP exposure — security remediation required before release.{% endif %}
</p>

</div>

<div class="page page-break">

{% set section_num = namespace(n=5) %}
{% for severity in ['critical', 'high', 'medium', 'low', 'info'] %}
{% set sev_findings = findings | selectattr('severity', 'eq', severity) | list %}
{% if sev_findings %}
<h2>{{ section_num.n }}. {{ severity | title }} Findings ({{ sev_findings | length }})</h2>
{% set section_num.n = section_num.n + 1 %}
{% for f in sev_findings %}
<div class="finding-card sev-{{ f.severity | upper }}">
  <div class="finding-header">
    <div class="finding-title">{{ f.rule_name or f.rule_id or "Untitled finding" }}</div>
    <span class="badge badge-{{ f.severity | upper }}">{{ f.severity | upper }}</span>
  </div>
  <div class="finding-meta">
    <div><span>Kind: </span><strong>{{ f.kind or "—" }}</strong></div>
    <div><span>Priority: </span><strong>{{ f.priority_score if f.priority_score is not none else "—" }}/10</strong></div>
    {% if f.cwe %}<div><span>CWE: </span><strong>{{ f.cwe | join(", ") }}</strong></div>{% endif %}
    {% if f.owasp %}<div style="grid-column:1/-1"><span>OWASP: </span><strong>{{ f.owasp | join(", ") }}</strong></div>{% endif %}
    {% if f.location.file %}
    <div class="finding-loc">{{ f.location.file }}{% if f.location.start_line %}:{{ f.location.start_line }}{% endif %}</div>
    {% endif %}
  </div>
  <p style="font-size:12px;margin-bottom:8px;">{{ f.message }}</p>
  {% if f.evidence and f.evidence[0].snippet %}
  <pre class="code-block">{{ f.evidence[0].snippet | e }}</pre>
  {% endif %}
  {% if f.remediation %}<div class="rec"><strong>Recommendation:</strong> {{ f.remediation }}</div>{% endif %}
</div>
{% endfor %}
{% endif %}
{% endfor %}

{% set secret_findings = findings | selectattr('kind', 'eq', 'secret') | list %}
<h2>{{ section_num.n }}. Secrets &amp; Sensitive Data Exposure</h2>
{% set section_num.n = section_num.n + 1 %}
{% if secret_findings %}
<p style="color:#e63946;font-weight:700;margin-bottom:12px;">{{ secret_findings | length }} secret(s) / sensitive value(s) detected. Rotate all exposed credentials immediately.</p>
<table>
  <tr><th>Rule</th><th>File</th><th>Line</th><th>Severity</th></tr>
  {% for f in secret_findings %}
  <tr>
    <td>{{ f.rule_name or f.rule_id or "—" }}</td>
    <td style="font-family:monospace;font-size:11px;word-break:break-all;">{{ f.location.file }}</td>
    <td>{{ f.location.start_line or "N/A" }}</td>
    <td><span class="badge badge-{{ f.severity | upper }}">{{ f.severity | upper }}</span></td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p style="color:#2a9d8f;">No hardcoded secrets or credentials detected.</p>
{% endif %}

{% set dep_findings = findings | selectattr('kind', 'eq', 'sca') | list %}
<h2>{{ section_num.n }}. Dependency Risks</h2>
{% set section_num.n = section_num.n + 1 %}
{% if dep_findings %}
<table>
  <tr><th>Vulnerability</th><th>Severity</th><th>Manifest File</th></tr>
  {% for f in dep_findings %}
  <tr>
    <td>{{ f.rule_name or f.rule_id or "—" }}</td>
    <td><span class="badge badge-{{ f.severity | upper }}">{{ f.severity | upper }}</span></td>
    <td style="font-family:monospace;font-size:11px;">{{ f.dependency.manifest if f.dependency else f.location.file }}</td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p style="color:#2a9d8f;">No known vulnerable dependencies detected.</p>
{% endif %}

{% if cwe_summary %}
<h2>{{ section_num.n }}. CWE Mapping</h2>
{% set section_num.n = section_num.n + 1 %}
<table>
  <tr><th>CWE</th><th>Count</th><th>Max Severity</th></tr>
  {% for row in cwe_summary %}
  <tr>
    <td><strong>{{ row.cwe }}</strong></td>
    <td>{{ row.count }}</td>
    <td><span class="badge badge-{{ row.max_severity | upper }}">{{ row.max_severity | upper }}</span></td>
  </tr>
  {% endfor %}
</table>
{% endif %}

<h2>{{ section_num.n }}. Remediation Plan</h2>
{% set rem_findings = findings | sort(attribute='priority_score', reverse=True) %}
{% if rem_findings %}
<p>Findings are ordered by priority score (highest first).</p>
<table>
  <tr><th>#</th><th>Finding</th><th>Priority</th><th>OWASP</th><th>Action</th></tr>
  {% for f in rem_findings %}
  <tr>
    <td>{{ loop.index }}</td>
    <td>{{ (f.rule_name or f.rule_id or "Untitled finding") | truncate(55) }}</td>
    <td><strong>{{ f.priority_score if f.priority_score is not none else "—" }}/10</strong></td>
    <td style="font-size:11px;">{{ (f.owasp | join(", ")) | truncate(20) if f.owasp else "—" }}</td>
    <td style="font-size:11px;">{{ (f.remediation or "—") | truncate(100) }}</td>
  </tr>
  {% endfor %}
</table>
{% else %}
<p>No remediation actions required.</p>
{% endif %}

<div class="conclusion">
  <p>This report was generated by the ZeroStrike Portal's SAST scan engine. All findings should be reviewed by a qualified security engineer before remediation. This report reflects a point-in-time snapshot and does not replace a full manual penetration test.</p>
  <p style="margin-top:12px;font-size:11px;color:#6c7a8d;">
    Scan ID: {{ scan.id }} &nbsp;|&nbsp; Generated: {{ report.generated_at.strftime('%Y-%m-%d %H:%M UTC') if report.generated_at else "—" }}
  </p>
</div>

</div>
</body>
</html>
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_pdf_report.py -v`
Expected: all 7 tests pass (4 pre-existing + 3 new from Task 7)

- [ ] **Step 3: Commit**

```bash
git add backend/app/reporting/templates/scan_report_executive.html.j2
git commit -m "feat: add ported Executive report template"
```

---

## Task 9: Sample-data fixture + report-templates router (settings + preview)

**Files:**
- Create: `backend/app/reporting/sample_data.py`
- Create: `backend/app/schemas/report_template.py`
- Create: `backend/app/routers/report_templates.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_report_templates.py`

- [ ] **Step 1: Write the failing test**

```python
from tests.test_auth_flow import register_and_login
from tests.test_users import _admin_headers


def _headers(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_preview_returns_html_for_both_templates(client):
    for template in ("standard", "executive"):
        r = client.get(f"/api/v1/report-templates/{template}/preview")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "Sample Project" in r.text
        assert "SQL Injection" in r.text


def test_get_default_report_template_settings(client):
    r = client.get("/api/v1/report-templates/settings")
    assert r.status_code == 200
    assert r.json()["default_report_template"] == "standard"


def test_only_admin_can_update_default_report_template(client):
    owner = register_and_login(client, email="rt-owner@zerostrike.dev")
    r = client.put(
        "/api/v1/report-templates/settings",
        json={"default_report_template": "executive"},
        headers=_headers(owner),
    )
    assert r.status_code == 403

    admin_headers = _admin_headers(client, email="rt-admin@zerostrike.dev")
    r = client.put(
        "/api/v1/report-templates/settings",
        json={"default_report_template": "executive"},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["default_report_template"] == "executive"

    r = client.get("/api/v1/report-templates/settings")
    assert r.json()["default_report_template"] == "executive"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_report_templates.py -v`
Expected: FAIL — `404` (no such route registered yet)

- [ ] **Step 3: Create the sample-data fixture**

```python
"""Hand-built sample Scan/Report/Finding data — powers the report-template preview
endpoint (GET /report-templates/{template}/preview), which isn't scoped to any real
project. Deliberately fake, obviously-labeled data — never a real project's findings.
"""

from datetime import datetime, timezone

from app.core.priority import compute_priority
from app.models.finding import EvidenceEmbedded, Finding, LocationEmbedded
from app.models.report import Report, ScanStatsEmbedded
from app.models.scan import Scan

_SAMPLE_AT = datetime(2026, 1, 15, 9, 30, tzinfo=timezone.utc)
_SAMPLE_SCAN_ID = "000000000000000000000001"
_SAMPLE_REPORT_ID = "000000000000000000000002"

_SAMPLE_FINDINGS_RAW = [
    dict(
        rule_id="SAMPLE-001", rule_name="SQL Injection", severity="critical", confidence="high",
        kind="sast", message="Untrusted input flows into a SQL query.", file="app/db.py", line=42,
        owasp=["A03:2025"], cwe=["CWE-89"],
        snippet='cursor.execute("SELECT * FROM users WHERE id = " + id)',
        remediation="Use parameterized queries.",
    ),
    dict(
        rule_id="SAMPLE-002", rule_name="AWS Access Key", severity="high", confidence="high",
        kind="secret", message="AWS access key ID detected in a config file.", file="config/.env",
        line=3, owasp=[], cwe=["CWE-798"], snippet=None,
        remediation="Rotate the key and load it from a secret manager.",
    ),
    dict(
        rule_id="SAMPLE-003", rule_name="Vulnerable Dependency", severity="medium", confidence="high",
        kind="sca", message="A dependency has a known vulnerability.", file="package-lock.json",
        line=None, owasp=["A06:2025"], cwe=["CWE-1321"], snippet=None,
        remediation="Upgrade to the patched version.",
    ),
    dict(
        rule_id="SAMPLE-004", rule_name="Debug Mode Enabled", severity="low", confidence="medium",
        kind="config", message="Debug mode is enabled and may leak sensitive data in production.",
        file="settings.py", line=12, owasp=["A05:2025"], cwe=["CWE-489"], snippet="DEBUG = True",
        remediation="Set DEBUG = False in production settings.",
    ),
    dict(
        rule_id="SAMPLE-005", rule_name="Outdated TLS Version", severity="info", confidence="low",
        kind="config", message="Server accepts TLS 1.0 connections.", file="nginx.conf", line=8,
        owasp=[], cwe=[], snippet=None, remediation="Disable TLS versions below 1.2.",
    ),
]


def _sample_finding(raw: dict) -> Finding:
    priority_score, priority_tier = compute_priority(raw["severity"], raw["owasp"], raw["confidence"])
    return Finding(
        scan_id=_SAMPLE_SCAN_ID,
        project_id="sample",
        rule_id=raw["rule_id"],
        rule_name=raw["rule_name"],
        severity=raw["severity"],
        confidence=raw["confidence"],
        kind=raw["kind"],
        message=raw["message"],
        location=LocationEmbedded(file=raw["file"], start_line=raw["line"]),
        evidence=[EvidenceEmbedded(snippet=raw["snippet"])] if raw["snippet"] else [],
        owasp=raw["owasp"],
        cwe=raw["cwe"],
        remediation=raw["remediation"],
        priority_score=priority_score,
        priority_tier=priority_tier,
        created_at=_SAMPLE_AT,
    )


def build_sample_report() -> tuple[Scan, Report, list[Finding]]:
    """A fixed, obviously-fake dataset — never a real project's findings."""
    scan = Scan(
        id=_SAMPLE_SCAN_ID,
        project_id="sample",
        scan_type="cloud",
        status="completed",
        scan_label="Sample Scan",
        repo_url="https://github.com/sample-org/sample-repo",
        branch="main",
        scanner_version="v0.1.0-sample",
        git_commit="abc123def456abc123def456abc123def456abc",
        hostname="sample-runner",
        started_at=_SAMPLE_AT,
        completed_at=_SAMPLE_AT,
        created_at=_SAMPLE_AT,
        updated_at=_SAMPLE_AT,
    )
    findings = [_sample_finding(raw) for raw in _SAMPLE_FINDINGS_RAW]
    by_severity: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for f in findings:
        by_severity[f.severity] = by_severity.get(f.severity, 0) + 1
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    report = Report(
        id=_SAMPLE_REPORT_ID,
        scan_id=_SAMPLE_SCAN_ID,
        project_id="sample",
        scanner_version="v0.1.0-sample",
        started_at=_SAMPLE_AT,
        duration_ms=8400,
        branch="main",
        git_commit="abc123def456abc123def456abc123def456abc",
        hostname="sample-runner",
        stats=ScanStatsEmbedded(
            files_scanned=37,
            total_findings=len(findings),
            by_severity=by_severity,
            by_kind=by_kind,
        ),
        json_uploaded_at=_SAMPLE_AT,
        generated_at=_SAMPLE_AT,
    )
    return scan, report, findings
```

- [ ] **Step 4: Create the settings request/response schemas**

```python
from pydantic import BaseModel

from app.models.workspace_settings import ReportTemplate


class ReportTemplateSettingsResponse(BaseModel):
    default_report_template: ReportTemplate


class ReportTemplateSettingsUpdateRequest(BaseModel):
    default_report_template: ReportTemplate
```

- [ ] **Step 5: Create the router**

```python
from fastapi import APIRouter, Depends, Response

from app.core.deps import require_admin
from app.models.user import User
from app.models.workspace_settings import ReportTemplate
from app.reporting import sample_data
from app.schemas.report_template import ReportTemplateSettingsResponse, ReportTemplateSettingsUpdateRequest
from app.services import pdf_report_service, report_template_service

router = APIRouter(prefix="/report-templates", tags=["report-templates"])


@router.get("/settings", response_model=ReportTemplateSettingsResponse)
async def get_report_template_settings():
    settings = await report_template_service.get_workspace_settings()
    return ReportTemplateSettingsResponse(default_report_template=settings.default_report_template)


@router.put("/settings", response_model=ReportTemplateSettingsResponse)
async def update_report_template_settings(
    payload: ReportTemplateSettingsUpdateRequest, user: User = Depends(require_admin)
):
    settings = await report_template_service.set_default_report_template(payload.default_report_template)
    return ReportTemplateSettingsResponse(default_report_template=settings.default_report_template)


@router.get("/{template}/preview")
async def preview_report_template(template: ReportTemplate):
    scan, report, findings = sample_data.build_sample_report()
    html = pdf_report_service.render_scan_report_html(
        scan, report, findings, template, project_name="Sample Project (sample data)"
    )
    return Response(content=html, media_type="text/html")
```

- [ ] **Step 6: Register the router**

In `backend/app/main.py`, find:

```python
from app.routers import (
    admin_downloads,
    api_keys,
    audit_logs,
    auth,
    connections,
    dashboard,
    downloads,
    projects,
    repo_credentials,
    scanner_scans,
    scans,
    users,
)
```

Replace with:

```python
from app.routers import (
    admin_downloads,
    api_keys,
    audit_logs,
    auth,
    connections,
    dashboard,
    downloads,
    projects,
    repo_credentials,
    report_templates,
    scanner_scans,
    scans,
    users,
)
```

Then find:

```python
    app.include_router(downloads.router, prefix="/api/v1")
    app.include_router(admin_downloads.router, prefix="/api/v1")
```

Replace with:

```python
    app.include_router(downloads.router, prefix="/api/v1")
    app.include_router(admin_downloads.router, prefix="/api/v1")
    app.include_router(report_templates.router, prefix="/api/v1")
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd backend && ./.venv/Scripts/pytest tests/test_report_templates.py -v`
Expected: 3 passed

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && ./.venv/Scripts/pytest -v`
Expected: all tests pass, no regressions

- [ ] **Step 9: Lint**

Run: `cd backend && ./.venv/Scripts/ruff check .`
Expected: no errors (fix any line-length/import-order issues it flags before committing)

- [ ] **Step 10: Commit**

```bash
git add backend/app/reporting/sample_data.py backend/app/schemas/report_template.py backend/app/routers/report_templates.py backend/app/main.py backend/tests/test_report_templates.py
git commit -m "feat: add report template settings API and sample-data preview endpoint"
```

---

## Task 10: Frontend priority metadata + API types

**Files:**
- Create: `frontend/lib/priority.ts`
- Modify: `frontend/lib/api/findings.ts`

- [ ] **Step 1: Create `lib/priority.ts`**

```typescript
// Mirrors lib/owasp.ts — priority tier metadata for the filter dropdown and the
// per-finding priority badge. Independent of severity: see backend/app/core/priority.py.
export type PriorityTier = "critical" | "high" | "medium" | "low";

export const PRIORITY_TIERS: PriorityTier[] = ["critical", "high", "medium", "low"];

export const PRIORITY_LABELS: Record<PriorityTier, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

export const PRIORITY_CLASS: Record<PriorityTier, string> = {
  critical: "text-severity-critical",
  high: "text-severity-high",
  medium: "text-severity-medium",
  low: "text-severity-low",
};
```

(As with `lib/owasp.ts`, this is plain constant data with no branches — no dedicated test, per this project's own convention of not testing trivial lookup tables.)

- [ ] **Step 2: Update the Finding type and listFindings()**

In `frontend/lib/api/findings.ts`, find:

```typescript
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type FindingKind = "sast" | "secret" | "sca" | "config";
```

Replace with:

```typescript
import type { PriorityTier } from "@/lib/priority";

export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type FindingKind = "sast" | "secret" | "sca" | "config";
```

Then find:

```typescript
  severity: Severity | null;
  confidence: string | null;
  message: string;
```

Replace with:

```typescript
  severity: Severity | null;
  confidence: string | null;
  priority_score: number | null;
  priority_tier: PriorityTier | null;
  message: string;
```

Then find:

```typescript
export function listFindings(
  scanId: string,
  opts: { severity?: Severity; kind?: FindingKind; owasp?: string; page?: number; pageSize?: number } = {}
) {
  const params = new URLSearchParams();
  if (opts.severity) params.set("severity", opts.severity);
  if (opts.kind) params.set("kind", opts.kind);
  if (opts.owasp) params.set("owasp", opts.owasp);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 50));
  return apiFetch<Page<Finding>>(`/scans/${scanId}/findings?${params.toString()}`);
}
```

Replace with:

```typescript
export function listFindings(
  scanId: string,
  opts: {
    severity?: Severity;
    kind?: FindingKind;
    owasp?: string;
    priority?: PriorityTier;
    page?: number;
    pageSize?: number;
  } = {}
) {
  const params = new URLSearchParams();
  if (opts.severity) params.set("severity", opts.severity);
  if (opts.kind) params.set("kind", opts.kind);
  if (opts.owasp) params.set("owasp", opts.owasp);
  if (opts.priority) params.set("priority", opts.priority);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.pageSize ?? 50));
  return apiFetch<Page<Finding>>(`/scans/${scanId}/findings?${params.toString()}`);
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors from these two files (pre-existing errors in unrelated files, if any, are out of scope)

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/priority.ts frontend/lib/api/findings.ts
git commit -m "feat: add priority tier metadata and wire it into the findings API client"
```

---

## Task 11: Frontend report-template API client + Project type

**Files:**
- Create: `frontend/lib/api/report-templates.ts`
- Modify: `frontend/lib/api/projects.ts`

- [ ] **Step 1: Create `lib/api/report-templates.ts`**

```typescript
import { apiFetch } from "./client";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

export type ReportTemplateId = "standard" | "executive";

export function getWorkspaceReportTemplate() {
  return apiFetch<{ default_report_template: ReportTemplateId }>("/report-templates/settings");
}

export function updateWorkspaceReportTemplate(template: ReportTemplateId) {
  return apiFetch<{ default_report_template: ReportTemplateId }>("/report-templates/settings", {
    method: "PUT",
    body: JSON.stringify({ default_report_template: template }),
  });
}

// No auth required (sample data only) — used directly as an <iframe src>.
export function reportTemplatePreviewUrl(template: ReportTemplateId) {
  return `${API_BASE_URL}/report-templates/${template}/preview`;
}
```

- [ ] **Step 2: Add `report_template` to the Project type and update patch**

In `frontend/lib/api/projects.ts`, find:

```typescript
  scan_count: number;
  last_scan_at: string | null;
  created_at: string;
  updated_at: string;
  my_role: "owner" | "collaborator" | "admin";
```

Replace with:

```typescript
  scan_count: number;
  last_scan_at: string | null;
  report_template: "standard" | "executive" | null;
  created_at: string;
  updated_at: string;
  my_role: "owner" | "collaborator" | "admin";
```

Then find:

```typescript
export function updateProject(
  id: string,
  patch: { name?: string; description?: string; is_archived?: boolean }
) {
  return apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
}
```

Replace with:

```typescript
export function updateProject(
  id: string,
  patch: {
    name?: string;
    description?: string;
    is_archived?: boolean;
    report_template?: "inherit" | "standard" | "executive";
  }
) {
  return apiFetch<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors from these two files

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/api/report-templates.ts frontend/lib/api/projects.ts
git commit -m "feat: add report-template settings API client and Project.report_template"
```

---

## Task 12: Shared ReportTemplatePicker component

**Files:**
- Create: `frontend/components/reports/report-template-picker.tsx`

- [ ] **Step 1: Create the component**

```tsx
"use client";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { reportTemplatePreviewUrl, type ReportTemplateId } from "@/lib/api/report-templates";

const TEMPLATES: { id: ReportTemplateId; label: string; description: string }[] = [
  { id: "standard", label: "Standard", description: "Plain, tabular PDF report." },
  {
    id: "executive",
    label: "Executive",
    description: "Branded cover page, risk banner, and OWASP compliance grid.",
  },
];

export type ReportTemplateValue = ReportTemplateId | "inherit";

// Two small preview windows (rendered from fixed sample data via the backend's preview
// endpoint) plus a select to change the active choice. Used both in Settings (workspace
// default, allowInherit=false) and a Project's Overview tab (allowInherit=true).
export function ReportTemplatePicker({
  value,
  onChange,
  allowInherit = false,
}: {
  value: ReportTemplateValue;
  onChange: (value: ReportTemplateValue) => void;
  allowInherit?: boolean;
}) {
  return (
    <div className="space-y-4">
      <Select value={value} onValueChange={(v) => v && onChange(v as ReportTemplateValue)}>
        <SelectTrigger size="sm" className="w-full sm:w-64">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {allowInherit && <SelectItem value="inherit">Inherit workspace default</SelectItem>}
          {TEMPLATES.map((t) => (
            <SelectItem key={t.id} value={t.id}>
              {t.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {TEMPLATES.map((t) => (
          <div key={t.id} className="space-y-2">
            <p className="text-sm font-medium">
              {t.label}
              {value === t.id ? " (selected)" : ""}
            </p>
            <p className="text-xs text-muted-foreground">{t.description}</p>
            <div className="h-64 w-full overflow-hidden rounded-lg border border-border bg-white">
              <iframe
                src={reportTemplatePreviewUrl(t.id)}
                title={`${t.label} report preview`}
                className="h-[600px] w-[250%] origin-top-left scale-[0.4]"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors

- [ ] **Step 3: Commit**

```bash
git add frontend/components/reports/report-template-picker.tsx
git commit -m "feat: add shared report template picker with live preview windows"
```

---

## Task 13: Wire the picker into Settings → Report Templates

**Files:**
- Modify: `frontend/app/(dashboard)/settings/report-templates/page.tsx`

- [ ] **Step 1: Replace the stub page**

Replace the entire contents of `frontend/app/(dashboard)/settings/report-templates/page.tsx` with:

```tsx
"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ApiError } from "@/lib/api/client";
import { getWorkspaceReportTemplate, updateWorkspaceReportTemplate } from "@/lib/api/report-templates";
import {
  ReportTemplatePicker,
  type ReportTemplateValue,
} from "@/components/reports/report-template-picker";
import { Skeleton } from "@/components/ui/skeleton";

export default function ReportTemplatesSettingsPage() {
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["settings", "report-template"],
    queryFn: getWorkspaceReportTemplate,
  });

  const mutation = useMutation({
    mutationFn: (template: "standard" | "executive") => updateWorkspaceReportTemplate(template),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "report-template"] });
      toast.success("Default report template updated");
    },
    onError: (err) =>
      toast.error(err instanceof ApiError ? err.message : "Failed to update default report template"),
  });

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-lg font-semibold">Report Templates</h2>
        <p className="text-sm text-muted-foreground">
          Customize the layout and branding of generated PDF reports.
        </p>
      </div>
      {isLoading || !data ? (
        <Skeleton className="h-64 w-full" />
      ) : (
        <ReportTemplatePicker
          value={data.default_report_template}
          onChange={(v) => mutation.mutate(v as "standard" | "executive")}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 2: Verify it builds**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors

- [ ] **Step 3: Commit**

```bash
git add "frontend/app/(dashboard)/settings/report-templates/page.tsx"
git commit -m "feat: wire workspace default report template into Settings page"
```

---

## Task 14: Wire the picker into Project Overview

**Files:**
- Modify: `frontend/app/(dashboard)/projects/[projectId]/page.tsx`

- [ ] **Step 1: Add the import**

Find:

```tsx
import { ProjectOwaspSection } from "@/components/projects/project-owasp-section";
```

Replace with:

```tsx
import { ProjectOwaspSection } from "@/components/projects/project-owasp-section";
import {
  ReportTemplatePicker,
  type ReportTemplateValue,
} from "@/components/reports/report-template-picker";
```

- [ ] **Step 2: Add the mutation inside `OverviewTab`**

Find:

```tsx
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const deleteMutation = useMutation({
```

Replace with:

```tsx
  const updateTemplate = useMutation({
    mutationFn: (template: ReportTemplateValue) => updateProject(projectId, { report_template: template }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["projects", projectId] });
      toast.success("Report template updated");
    },
    onError: (err) => toast.error(err instanceof ApiError ? err.message : "Failed to update report template"),
  });

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [confirmName, setConfirmName] = useState("");
  const deleteMutation = useMutation({
```

- [ ] **Step 3: Add the card before the Danger Zone**

Find:

```tsx
      {canManage(project.my_role) && (
        <Card className="border-destructive/30">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-destructive">Danger Zone</CardTitle>
          </CardHeader>
```

Replace with:

```tsx
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-normal text-muted-foreground">Report Template</CardTitle>
        </CardHeader>
        <CardContent>
          <ReportTemplatePicker
            value={(project.report_template ?? "inherit") as ReportTemplateValue}
            onChange={(v) => updateTemplate.mutate(v)}
            allowInherit
          />
        </CardContent>
      </Card>

      {canManage(project.my_role) && (
        <Card className="border-destructive/30">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-destructive">Danger Zone</CardTitle>
          </CardHeader>
```

- [ ] **Step 4: Verify it builds**

Run: `cd frontend && npx tsc --noEmit`
Expected: no new errors

- [ ] **Step 5: Commit**

```bash
git add "frontend/app/(dashboard)/projects/[projectId]/page.tsx"
git commit -m "feat: let a project override its report template from the Overview tab"
```

---

## Task 15: Scan detail page — dropdown filters + real priority display

**Files:**
- Modify: `frontend/app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx`

This is the last piece: replace the fake `SEVERITY_SCORE` lookup and the toggle-button filter row with real priority data and `FilterBar` dropdowns.

- [ ] **Step 1: Update imports and drop the fake score table**

Find:

```tsx
import { OwaspChart } from "@/components/common/owasp-chart";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { StatCard } from "@/components/common/stat-card";
```

Replace with:

```tsx
import { OwaspChart } from "@/components/common/owasp-chart";
import { FilterBar } from "@/components/common/filter-bar";
import { DataTableCard } from "@/components/common/data-table-card";
import { EmptyState } from "@/components/common/empty-state";
import { StatCard } from "@/components/common/stat-card";
```

Find:

```tsx
import { owaspChartData, OWASP_TITLES } from "@/lib/owasp";
import { listFindings, type Finding, type FindingKind, type Severity } from "@/lib/api/findings";
```

Replace with:

```tsx
import { owaspChartData, OWASP_TITLES } from "@/lib/owasp";
import { PRIORITY_TIERS, PRIORITY_LABELS, PRIORITY_CLASS, type PriorityTier } from "@/lib/priority";
import { listFindings, type Finding, type FindingKind, type Severity } from "@/lib/api/findings";
```

Find:

```tsx
const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const KINDS: FindingKind[] = ["sast", "secret", "sca", "config"];

// Not a real CVSS score — a conventional severity-tier approximation, shown so the
// findings list has the "score" column the design calls for without fabricating
// false precision.
const SEVERITY_SCORE: Record<Severity, number> = { critical: 9.5, high: 7.5, medium: 5, low: 2.5, info: 1 };
const SEVERITY_SCORE_CLASS: Record<Severity, string> = {
  critical: "text-severity-critical",
  high: "text-severity-high",
  medium: "text-severity-medium",
  low: "text-severity-low",
  info: "text-severity-info",
};
```

Replace with:

```tsx
const SEVERITIES: Severity[] = ["critical", "high", "medium", "low", "info"];
const KINDS: FindingKind[] = ["sast", "secret", "sca", "config"];
const ALL = "__all__";
```

- [ ] **Step 2: Update `FindingItem` to show the real priority score**

Find:

```tsx
        <div className="hidden shrink-0 gap-6 text-right text-xs md:flex">
          <div>
            <p className="text-muted-foreground">Category</p>
            <p className="font-medium">{finding.category ?? "—"}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Score</p>
            <p className={cn("font-mono font-bold", finding.severity && SEVERITY_SCORE_CLASS[finding.severity])}>
              {finding.severity ? SEVERITY_SCORE[finding.severity].toFixed(1) : "—"}
            </p>
          </div>
        </div>
```

Replace with:

```tsx
        <div className="hidden shrink-0 gap-6 text-right text-xs md:flex">
          <div>
            <p className="text-muted-foreground">Category</p>
            <p className="font-medium">{finding.category ?? "—"}</p>
          </div>
          <div>
            <p className="text-muted-foreground">Priority</p>
            <p className={cn("font-mono font-bold", finding.priority_tier && PRIORITY_CLASS[finding.priority_tier])}>
              {finding.priority_score != null ? finding.priority_score.toFixed(1) : "—"}
              {finding.priority_tier ? ` (${PRIORITY_LABELS[finding.priority_tier]})` : ""}
            </p>
          </div>
        </div>
```

- [ ] **Step 3: Add priority filter state**

Find:

```tsx
  const [severity, setSeverity] = useState<Severity>();
  const [kind, setKind] = useState<FindingKind>();
  const [owaspFilter, setOwaspFilter] = useState<string>();
```

Replace with:

```tsx
  const [severity, setSeverity] = useState<Severity>();
  const [kind, setKind] = useState<FindingKind>();
  const [owaspFilter, setOwaspFilter] = useState<string>();
  const [priority, setPriority] = useState<PriorityTier>();
```

- [ ] **Step 4: Pass the new filter into the query**

Find:

```tsx
  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ["scans", scanId, "findings", severity ?? "", kind ?? "", owaspFilter ?? ""],
    queryFn: () => listFindings(scanId, { severity, kind, owasp: owaspFilter }),
    enabled: completed,
    retry: false,
  });
```

Replace with:

```tsx
  const { data: findings, isLoading: findingsLoading } = useQuery({
    queryKey: ["scans", scanId, "findings", severity ?? "", kind ?? "", owaspFilter ?? "", priority ?? ""],
    queryFn: () => listFindings(scanId, { severity, kind, owasp: owaspFilter, priority }),
    enabled: completed,
    retry: false,
  });
```

- [ ] **Step 5: Replace the toggle-button filter row with `FilterBar` dropdowns**

Find:

```tsx
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm text-muted-foreground">Filter:</span>
              {SEVERITIES.map((s) => (
                <Button
                  key={s}
                  size="xs"
                  variant={severity === s ? "secondary" : "ghost"}
                  onClick={() => setSeverity(severity === s ? undefined : s)}
                >
                  {s}
                </Button>
              ))}
              <span className="mx-1 text-muted-foreground">·</span>
              {KINDS.map((k) => (
                <Button
                  key={k}
                  size="xs"
                  variant={kind === k ? "secondary" : "ghost"}
                  onClick={() => setKind(kind === k ? undefined : k)}
                >
                  {k}
                </Button>
              ))}
              {owaspFilter && (
                <>
                  <span className="mx-1 text-muted-foreground">·</span>
                  <Badge variant="secondary" className="gap-1">
                    OWASP: {OWASP_TITLES[owaspFilter] ?? owaspFilter}
                    <button type="button" onClick={() => setOwaspFilter(undefined)} aria-label="Clear OWASP filter">
                      <X className="size-3" />
                    </button>
                  </Badge>
                </>
              )}
            </div>
            <div className="relative w-full sm:w-64">
              <Search className="absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search findings…"
                className="pl-8"
              />
            </div>
          </div>
```

Replace with:

```tsx
          <FilterBar
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search findings…"
            facets={[
              {
                type: "select",
                value: severity ?? ALL,
                onChange: (v) => setSeverity(v === ALL ? undefined : (v as Severity)),
                placeholder: "Severity",
                options: [{ value: ALL, label: "All severities" }, ...SEVERITIES.map((s) => ({ value: s, label: s }))],
              },
              {
                type: "select",
                value: kind ?? ALL,
                onChange: (v) => setKind(v === ALL ? undefined : (v as FindingKind)),
                placeholder: "Kind",
                options: [{ value: ALL, label: "All kinds" }, ...KINDS.map((k) => ({ value: k, label: k }))],
              },
              {
                type: "select",
                value: owaspFilter ?? ALL,
                onChange: (v) => setOwaspFilter(v === ALL ? undefined : v),
                placeholder: "OWASP category",
                options: [
                  { value: ALL, label: "All OWASP categories" },
                  ...Object.entries(OWASP_TITLES).map(([code, title]) => ({ value: code, label: `${code} — ${title}` })),
                ],
              },
              {
                type: "select",
                value: priority ?? ALL,
                onChange: (v) => setPriority(v === ALL ? undefined : (v as PriorityTier)),
                placeholder: "Priority",
                options: [
                  { value: ALL, label: "All priorities" },
                  ...PRIORITY_TIERS.map((p) => ({ value: p, label: PRIORITY_LABELS[p] })),
                ],
              },
            ]}
          />
```

- [ ] **Step 6: Remove now-unused imports**

Find:

```tsx
import { ChevronRight, Download, RefreshCw, Search, Sparkles, Wand2, X } from "lucide-react";
```

Replace with:

```tsx
import { ChevronRight, Download, RefreshCw, Sparkles, Wand2 } from "lucide-react";
```

(`Search` and `X` were only used by the removed manual search box and OWASP-clear badge — `FilterBar` renders its own search icon and there's no more standalone clearable badge. The `Badge` import stays if still used elsewhere on the page — check with the next step before removing it.)

- [ ] **Step 7: Verify no leftover unused imports/vars**

Run: `cd frontend && npx eslint app/\(dashboard\)/projects/\[projectId\]/scans/\[scanId\]/page.tsx`
Expected: no `no-unused-vars` warnings. If `Badge` is flagged unused, remove its import line too.

- [ ] **Step 8: Typecheck and build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: both succeed with no new errors

- [ ] **Step 9: Manually verify in the browser**

Run: `cd frontend && npm run dev` (and `cd backend && ./.venv/Scripts/uvicorn app.main:app --reload` in another terminal)
Open a completed scan's detail page, confirm: the four filter dropdowns appear and each narrows the findings list; the OWASP chart's click-to-filter still updates the OWASP dropdown's selection; each finding row shows a real priority score (not the old flat per-severity number) and tier label.

- [ ] **Step 10: Commit**

```bash
git add "frontend/app/(dashboard)/projects/[projectId]/scans/[scanId]/page.tsx"
git commit -m "feat: dropdown severity/kind/OWASP/priority filters and real priority scores on the scan report page"
```

---

## Task 16: Final full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend test suite**

Run: `cd backend && ./.venv/Scripts/pytest -v`
Expected: all tests pass

- [ ] **Step 2: Backend lint**

Run: `cd backend && ./.venv/Scripts/ruff check .`
Expected: no errors

- [ ] **Step 3: Frontend build**

Run: `cd frontend && npm run build`
Expected: build succeeds

- [ ] **Step 4: Frontend lint**

Run: `cd frontend && npm run lint`
Expected: no errors

- [ ] **Step 5: Manual smoke test of the two report templates**

With both servers running (`uvicorn` + `npm run dev`), as an admin user: open Settings → Report Templates, confirm both preview windows render distinct layouts (plain table vs. branded cover/OWASP-grid) with "Sample Project (sample data)" visible in both. Open a project's Overview tab, switch its report template to "Executive," open a completed scan, click "Generate Report," and confirm the downloaded PDF uses the branded layout (cover page, risk banner, OWASP grid) rather than the plain one.

If any step fails, fix the specific regression and re-run the relevant command above before considering the plan complete.

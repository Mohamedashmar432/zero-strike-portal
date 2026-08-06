"""Deterministic DB -> Markdown remediation brief.

The load-bearing property is idempotence: two renders of the same documents must be byte-identical
apart from the single generated-at line, so the artifact can be regenerated freely and two versions
can be diffed meaningfully.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.models.ai_finding_insight import AIFindingInsight
from app.models.ai_fix_proposal import AIFixProposal
from app.models.finding import EvidenceEmbedded, Finding, LocationEmbedded
from app.models.finding_comment import FindingComment
from app.models.project import Project
from app.models.scan import Scan
from app.models.user import User
from app.services import remediation_brief_service as brief

FIXED_AT = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)


async def _scan(project_name="Acme API"):
    now = datetime.now(timezone.utc)
    project = Project(name=project_name, owner_id="u1", created_at=now, updated_at=now)
    await project.insert()
    scan = Scan(
        project_id=str(project.id), scan_type="cloud", status="completed", branch="main",
        git_commit="abc1234", scanner_version="1.2.3", repo_url="https://github.com/o/r.git",
        completed_at=FIXED_AT, created_at=now, updated_at=now,
    )
    await scan.insert()
    return project, scan


async def _finding(scan, *, severity="high", file="app.py", line=10, fingerprint="fp1", rule="sql-injection"):
    f = Finding(
        scan_id=str(scan.id), project_id=scan.project_id, fingerprint=fingerprint, rule_id=rule,
        rule_name="SQL Injection", message="tainted query reaches execute()", kind="sast",
        severity=severity, language="python", cwe=["CWE-89"], owasp=["A03:2021"],
        location=LocationEmbedded(file=file, start_line=line, end_line=line),
        evidence=[EvidenceEmbedded(snippet="q = 'SELECT ' + uid", start_line=line, end_line=line)],
        created_at=datetime.now(timezone.utc),
    )
    await f.insert()
    return f


async def _proposal(scan, finding, **kw):
    defaults = dict(
        can_fix=True, confidence_score=91.0, original_code="q = 'SELECT ' + uid",
        patched_code="q = 'SELECT ?'", file_path=finding.location.file,
        explanation="Use a bound parameter.", review_state="proposed",
    )
    defaults.update(kw)
    p = AIFixProposal(
        finding_id=str(finding.id), scan_id=str(scan.id), project_id=scan.project_id, **defaults
    )
    await p.insert()
    return p


# --- determinism ----------------------------------------------------------------------------


def test_two_renders_are_byte_identical(client):
    async def run():
        project, scan = await _scan()
        for i in range(4):
            f = await _finding(scan, fingerprint=f"fp{i}", file=f"m{i}.py", line=i + 1)
            await _proposal(scan, f)

        a = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        b = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert a == b

    asyncio.run(run())


def test_only_the_header_line_carries_a_timestamp(client):
    """If a wall-clock value leaked into the body, renders minutes apart would differ."""
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        await _proposal(scan, f)

        a = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        b = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT + timedelta(hours=5))
        differing = [x for x, y in zip(a.splitlines(), b.splitlines()) if x != y]
        assert len(differing) == 1
        assert differing[0].startswith("_Generated ")

    asyncio.run(run())


def test_findings_are_ordered_by_severity_then_path(client):
    """Ordering must come from the documents, not Mongo's insertion order."""
    async def run():
        project, scan = await _scan()
        for sev, path in [("low", "z.py"), ("critical", "b.py"), ("high", "a.py"), ("critical", "a.py")]:
            f = await _finding(scan, severity=sev, file=path, fingerprint=f"{sev}-{path}")
            await _proposal(scan, f)

        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        headings = [ln for ln in out.splitlines() if ln.startswith("### ")]
        assert headings == [
            "### CRITICAL — SQL Injection",
            "### CRITICAL — SQL Injection",
            "### HIGH — SQL Injection",
            "### LOW — SQL Injection",
        ]
        # Within equal severity, path ascending.
        assert out.index("`a.py`") < out.index("`b.py`")

    asyncio.run(run())


# --- content --------------------------------------------------------------------------------


def test_brief_includes_scan_metadata_and_the_patch(client):
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        await _proposal(scan, f)

        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "# Remediation brief — Acme API" in out
        assert "`abc1234`" in out and "`1.2.3`" in out
        assert "CWE-89" in out and "A03:2021" in out
        assert "tainted query reaches execute()" in out
        assert "```diff" in out
        assert "Use a bound parameter." in out
        assert "Awaiting review" in out

    asyncio.run(run())


def test_stage_artifacts_explain_the_review_state(client):
    """A reader should learn *why* a finding needs a human without opening the app."""
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        await _proposal(
            scan, f, can_fix=False, review_state="manual_review", confidence_score=0.0,
            original_code=None, patched_code=None,
            manual_review_reason="Rotate the credential first.",
            triage={"eligible": False, "reason": "Rotate the credential first.", "strategy": "rotate-secret"},
        )
        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "**Triage** — not auto-fixable (rotate-secret)" in out
        assert "Needs manual remediation" in out

    asyncio.run(run())


def test_critique_verdict_is_rendered(client):
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        await _proposal(
            scan, f,
            critique={"verdict": "pass", "adjusted_confidence": 84, "redrafted": True,
                      "reasoning": "Bound parameter is correct.", "issues": []},
        )
        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "verdict **pass**" in out
        assert "reviewer confidence 84/100" in out
        assert "redrafted once" in out

    asyncio.run(run())


def test_uncritiqued_proposal_says_so_rather_than_implying_it_passed(client):
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        await _proposal(scan, f, critique={"skipped": "disabled"})
        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "**AI review** — not performed (disabled)" in out

    asyncio.run(run())


def test_validation_evidence_is_rendered_explicitly(client):
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        await _proposal(
            scan, f, review_state="pr_open", pr_url="https://github.com/o/r/pull/7",
            validation={"target_cleared": True, "new_finding_count": 0, "scope_ok": True,
                        "baseline_count": 12, "post_count": 11, "scanner_version": "1.2.3"},
        )
        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "Target finding resolved on re-scan: **yes**" in out
        assert "New findings introduced: **0**" in out
        assert "https://github.com/o/r/pull/7" in out

    asyncio.run(run())


def test_ai_insight_is_included_when_present(client):
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        await _proposal(scan, f)
        await AIFindingInsight(
            fingerprint="fp1", project_id=scan.project_id, explanation="Reachable from the HTTP layer.",
            is_false_positive=False,
        ).insert()

        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "Reachable from the HTTP layer." in out

    asyncio.run(run())


def test_repo_content_cannot_break_out_of_a_code_fence(client):
    """A snippet containing a fence must not terminate the block and let repo text render as
    markdown -- the fence widens instead."""
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        f.evidence = [EvidenceEmbedded(snippet="before\n```\n# INJECTED HEADING\n", start_line=1)]
        await f.save()
        await _proposal(scan, f)

        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "````" in out  # widened fence

    asyncio.run(run())


def test_comments_render_with_their_author_names(client):
    """Regression: the author lookup used a User field that doesn't exist, so any brief for a scan
    with an authored comment 500'd. The original tests all had zero comments, which short-circuited
    the lookup entirely — hence this one seeds a real comment and a real user."""
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        p = await _proposal(scan, f)
        author = User(
            email="reviewer@zerostrike-qa.com", name="Ravi Reviewer", password_hash="x",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        await author.insert()
        await FindingComment(
            finding_id=str(f.id), scan_id=str(scan.id), project_id=scan.project_id,
            author_user_id=str(author.id), body="Confirmed exploitable in staging.",
            created_at=FIXED_AT,
        ).insert()

        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "Ravi Reviewer" in out
        assert "Confirmed exploitable in staging." in out
        assert str(p.id)  # proposal section rendered around it

    asyncio.run(run())


def test_a_comment_from_a_deleted_author_still_renders(client):
    """A stale author_user_id must degrade that one line to Unknown, not fail the whole brief."""
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        await _proposal(scan, f)
        await FindingComment(
            finding_id=str(f.id), scan_id=str(scan.id), project_id=scan.project_id,
            author_user_id="not-a-valid-object-id", body="orphaned note",
            created_at=FIXED_AT,
        ).insert()

        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "orphaned note" in out
        assert "Unknown" in out

    asyncio.run(run())


def test_scan_with_no_proposals_renders_a_clean_empty_state(client):
    async def run():
        project, scan = await _scan()
        await _finding(scan)
        out = await brief.render_scan_brief(str(scan.id), generated_at=FIXED_AT)
        assert "No fix proposals have been generated" in out
        assert "Findings in this scan: **1**" in out

    asyncio.run(run())


def test_missing_scan_returns_none(client):
    assert asyncio.run(brief.render_scan_brief("6890000000000000000000aa")) is None


# --- the PR-body caller ----------------------------------------------------------------------


def test_pr_body_variant_omits_the_diff_but_keeps_the_evidence(client):
    """The PR already shows the diff; the description must still carry the finding + validation."""
    async def run():
        project, scan = await _scan()
        f = await _finding(scan)
        p = await _proposal(
            scan, f, validation={"target_cleared": True, "new_finding_count": 0, "scope_ok": True}
        )
        section = brief.render_proposal_section(p, f, include_diff=False, heading_level=2)
        assert "```diff" not in section
        assert section.startswith("## HIGH — SQL Injection")
        assert "CWE-89" in section
        assert "Target finding resolved on re-scan: **yes**" in section

    asyncio.run(run())


# --- the endpoint ----------------------------------------------------------------------------


def test_brief_endpoint_serves_markdown_as_an_attachment(client):
    from tests.test_auth_flow import register_and_login

    tokens = register_and_login(client, email="brief-owner@zs.dev")
    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    project = client.post("/api/v1/projects", json={"name": "Brief Demo"}, headers=headers).json()

    async def seed():
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id=project["id"], scan_type="cloud", status="completed", branch="main",
            created_at=now, updated_at=now,
        )
        await scan.insert()
        return str(scan.id)

    scan_id = asyncio.run(seed())
    r = client.get(f"/api/v1/scans/{scan_id}/auto-fix/brief", headers=headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert f"zerostrike-remediation-{scan_id}.md" in r.headers["content-disposition"]
    assert r.text.startswith("# Remediation brief — Brief Demo")


def test_brief_endpoint_denies_a_non_member(client):
    from tests.test_auth_flow import register_and_login

    owner = register_and_login(client, email="brief-owner2@zs.dev")
    owner_headers = {"Authorization": f"Bearer {owner['access_token']}"}
    project = client.post("/api/v1/projects", json={"name": "Private"}, headers=owner_headers).json()

    async def seed():
        now = datetime.now(timezone.utc)
        scan = Scan(
            project_id=project["id"], scan_type="cloud", status="completed",
            created_at=now, updated_at=now,
        )
        await scan.insert()
        return str(scan.id)

    scan_id = asyncio.run(seed())
    outsider = register_and_login(client, email="brief-outsider@zs.dev")
    r = client.get(
        f"/api/v1/scans/{scan_id}/auto-fix/brief",
        headers={"Authorization": f"Bearer {outsider['access_token']}"},
    )
    assert r.status_code == 403

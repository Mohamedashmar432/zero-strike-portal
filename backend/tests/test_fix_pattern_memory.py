"""Per-project fix memory: what gets remembered, what gets read back, and what must not.

The security-relevant assertion here is that only pr_open (scanner-verified + human-approved)
patterns are ever fed back into a prompt. A dismissed patch is a patch a human rejected; showing
it to the next agent as an example would teach exactly the wrong thing.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from app.models.ai_fix_proposal import AIFixProposal
from app.models.finding import Finding, LocationEmbedded
from app.models.fix_pattern import FixPattern
from app.services import ai_remediation_service, fix_pattern_service


async def _finding(rule_id="sql-injection", project_id="p1"):
    f = Finding(
        scan_id="s1", project_id=project_id, fingerprint="fp1", rule_id=rule_id,
        rule_name="SQL Injection", message="m", kind="sast", language="python",
        location=LocationEmbedded(file="app.py", start_line=10),
        created_at=datetime.now(timezone.utc),
    )
    await f.insert()
    return f


async def _proposal(finding, project_id="p1", original="a = q + uid", patched="a = q, (uid,)"):
    p = AIFixProposal(
        finding_id=str(finding.id), scan_id="s1", project_id=project_id, can_fix=True,
        confidence_score=90, original_code=original, patched_code=patched, file_path="app.py",
        explanation="use a bound parameter", provider="anthropic", model_name="m",
    )
    await p.insert()
    return p


def test_accepted_fix_is_remembered_and_read_back(client):
    async def run():
        f = await _finding()
        p = await _proposal(f)
        await fix_pattern_service.record(p, f, "pr_open")

        examples = await fix_pattern_service.recent_accepted("p1", "sql-injection")
        assert len(examples) == 1
        assert examples[0]["original_code"] == "a = q + uid"
        assert examples[0]["patched_code"] == "a = q, (uid,)"
        assert examples[0]["language"] == "python"

    asyncio.run(run())


def test_dismissed_fix_is_recorded_but_never_read_back(client):
    """The load-bearing rule: a human rejected this patch, so it is not an example to follow."""
    async def run():
        f = await _finding()
        p = await _proposal(f)
        await fix_pattern_service.record(p, f, "dismissed")

        stored = await FixPattern.find(FixPattern.project_id == "p1").to_list()
        assert len(stored) == 1 and stored[0].outcome == "dismissed"  # kept for analytics
        assert await fix_pattern_service.recent_accepted("p1", "sql-injection") == []

    asyncio.run(run())


def test_memory_does_not_leak_across_projects(client):
    async def run():
        f = await _finding(project_id="p1")
        await fix_pattern_service.record(await _proposal(f, project_id="p1"), f, "pr_open")
        assert await fix_pattern_service.recent_accepted("p2", "sql-injection") == []

    asyncio.run(run())


def test_memory_is_scoped_to_the_rule(client):
    async def run():
        f = await _finding(rule_id="sql-injection")
        await fix_pattern_service.record(await _proposal(f), f, "pr_open")
        assert await fix_pattern_service.recent_accepted("p1", "path-traversal") == []

    asyncio.run(run())


def test_no_rule_id_reads_nothing(client):
    """Legacy findings have no rule_id; a read must not match every remembered row."""
    async def run():
        f = await _finding()
        await fix_pattern_service.record(await _proposal(f), f, "pr_open")
        assert await fix_pattern_service.recent_accepted("p1", None) == []

    asyncio.run(run())


def test_most_recent_examples_win_and_are_capped(client):
    async def run():
        f = await _finding()
        base = datetime.now(timezone.utc)
        for i in range(5):
            p = await _proposal(f, original=f"old-{i}", patched=f"new-{i}")
            pattern = await fix_pattern_service.record(p, f, "pr_open")
            await pattern.set({FixPattern.created_at: base + timedelta(minutes=i)})

        examples = await fix_pattern_service.recent_accepted("p1", "sql-injection")
        assert len(examples) == fix_pattern_service._MAX_EXAMPLES
        assert [e["patched_code"] for e in examples] == ["new-4", "new-3"]

    asyncio.run(run())


def test_incomplete_patterns_are_skipped(client):
    """A row with no patch text teaches nothing; it must not become an empty example."""
    async def run():
        f = await _finding()
        p = await _proposal(f)
        p.patched_code = None
        await p.save()
        await fix_pattern_service.record(p, f, "pr_open")
        assert await fix_pattern_service.recent_accepted("p1", "sql-injection") == []

    asyncio.run(run())


def test_oversized_code_is_clipped(client):
    """One huge historical patch must not crowd out the code actually under review."""
    async def run():
        f = await _finding()
        p = await _proposal(f, original="x" * 9000, patched="y" * 9000)
        await fix_pattern_service.record(p, f, "pr_open")
        example = (await fix_pattern_service.recent_accepted("p1", "sql-injection"))[0]
        assert len(example["original_code"]) < 9000
        assert example["original_code"].endswith("(truncated)")

    asyncio.run(run())


def test_reuse_counter_increments_when_an_example_is_served(client):
    async def run():
        f = await _finding()
        await fix_pattern_service.record(await _proposal(f), f, "pr_open")
        await fix_pattern_service.recent_accepted("p1", "sql-injection")
        await fix_pattern_service.recent_accepted("p1", "sql-injection")
        row = (await FixPattern.find(FixPattern.project_id == "p1").to_list())[0]
        assert row.times_reused == 2

    asyncio.run(run())


def test_examples_enter_the_bundle_as_untrusted_context(client):
    async def run():
        f = await _finding()
        prior = [{"file_path": "app.py", "original_code": "a", "patched_code": "b"}]
        bundle = ai_remediation_service._issue_bundle(f, "snippet", None, prior)
        assert bundle["previously_accepted_fixes_for_this_rule"] == prior
        # And absent entirely when there is no history, so the prompt stays lean.
        assert "previously_accepted_fixes_for_this_rule" not in ai_remediation_service._issue_bundle(
            f, "snippet", None, []
        )

    asyncio.run(run())

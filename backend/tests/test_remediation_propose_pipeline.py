"""The propose pipeline end to end at service level: triage -> draft -> critique -> persist.

Mocks the two LLM boundaries (ai_remediation_agent.run_agent, llm_client.get_completion) so the
stage wiring, the redraft loop, and the persisted per-stage artifacts are exercised without a
provider. Complements test_remediation_critic.py (which tests verdict handling in isolation).
"""

import asyncio
from datetime import datetime, timezone

from app.core.config import settings
from app.models.ai_fix_proposal import AIFixProposal
from app.models.ai_remediation_job import RemediationJob
from app.models.finding import DependencyEmbedded, EvidenceEmbedded, Finding, LocationEmbedded
from app.services import ai_remediation_agent, ai_remediation_service, llm_client

SNIPPET = "q = 'SELECT * FROM u WHERE id=' + uid"


async def _seed(file="app.py", kind="sast", dependency=None):  # returns (finding, job)
    now = datetime.now(timezone.utc)
    f = Finding(
        scan_id="s1", project_id="p1", fingerprint="fp1", rule_id="sql-injection",
        rule_name="SQL Injection", message="tainted query", kind=kind, severity="high",
        language="python", location=LocationEmbedded(file=file, start_line=10, end_line=10),
        evidence=[EvidenceEmbedded(snippet=SNIPPET, start_line=10, end_line=10)],
        dependency=dependency, created_at=now,
    )
    await f.insert()
    job = RemediationJob(
        kind="propose", project_id="p1", scan_id="s1", finding_ids=[str(f.id)],
        scope_key="s1:propose", trace_id="t1",
    )
    await job.insert()
    return f, job


def _mock_agent(monkeypatch, drafts):
    """drafts: list of (can_fix, confidence, patched) consumed in order, one per agent run."""
    calls = {"n": 0, "notes": []}
    queue = list(drafts)

    async def fake_run_agent(bundle, ctx, budgets, *, revision_note=None):
        calls["n"] += 1
        calls["notes"].append(revision_note)
        can_fix, confidence, patched = queue.pop(0) if queue else (True, 90.0, "fixed")
        return ai_remediation_service.SubmitFixProposalArgs(
            finding_id=bundle["finding_id"], can_fix=can_fix, confidence_score=confidence,
            file_path="app.py", original_code=SNIPPET if can_fix else None,
            patched_code=patched if can_fix else None, explanation="parameterize",
            patch_scope="single-file" if can_fix else "none",
        )

    monkeypatch.setattr(ai_remediation_agent, "run_agent", fake_run_agent)
    return calls


def _mock_critic(monkeypatch, verdicts):
    calls = {"n": 0}
    queue = list(verdicts)

    async def fake(messages, **kwargs):
        calls["n"] += 1
        return queue.pop(0) if queue else {"verdict": "pass"}

    monkeypatch.setattr(llm_client, "get_completion", fake)
    return calls


def _propose(finding, job):
    return asyncio.run(
        ai_remediation_service._propose_for_finding(finding, job, "main", "anthropic", "m")
    )


# --- triage gate ----------------------------------------------------------------------------


def test_secret_finding_is_triaged_out_without_any_llm_call(client, monkeypatch):
    """The headline saving: a hopeless finding costs zero tokens and gets a precise reason."""
    agent = _mock_agent(monkeypatch, [])
    critic = _mock_critic(monkeypatch, [])

    async def run():
        f, job = await _seed(file="config.py", kind="secret")
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert agent["n"] == 0, "the agent must not run for a triaged-out finding"
        assert critic["n"] == 0
        assert proposal.can_fix is False
        assert proposal.review_state == "manual_review"
        assert proposal.triage == {
            "eligible": False, "reason": proposal.manual_review_reason, "strategy": "rotate-secret",
        }
        assert "Rotate" in proposal.manual_review_reason
        assert proposal.critique is None  # nothing was critiqued, so no critique artifact

    asyncio.run(run())


def test_vendored_finding_is_triaged_out(client, monkeypatch):
    agent = _mock_agent(monkeypatch, [])
    _mock_critic(monkeypatch, [])

    async def run():
        f, job = await _seed(file="node_modules/lodash/index.js")
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert agent["n"] == 0
        assert proposal.triage["strategy"] == "none"
        assert proposal.review_state == "manual_review"

    asyncio.run(run())


def test_eligible_finding_reaches_the_agent(client, monkeypatch):
    agent = _mock_agent(monkeypatch, [(True, 90.0, "safe")])
    _mock_critic(monkeypatch, [{"verdict": "pass", "adjusted_confidence": 88}])

    async def run():
        f, job = await _seed()
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert agent["n"] == 1
        assert proposal.triage == {"eligible": True, "reason": None, "strategy": "code-patch"}
        assert proposal.review_state == "proposed"
        assert proposal.confidence_score == 88

    asyncio.run(run())


# --- critique + redraft ----------------------------------------------------------------------


def test_revise_verdict_triggers_exactly_one_redraft(client, monkeypatch):
    agent = _mock_agent(monkeypatch, [(True, 90.0, "first"), (True, 95.0, "second")])
    _mock_critic(
        monkeypatch,
        [
            {"verdict": "revise", "issues": ["use a bound parameter"]},
            {"verdict": "pass", "adjusted_confidence": 92},
        ],
    )

    async def run():
        f, job = await _seed()
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert agent["n"] == 2, "one draft + one redraft"
        assert agent["notes"][0] is None
        assert "use a bound parameter" in agent["notes"][1], "critic issues feed the revision note"
        assert proposal.patched_code == "second"
        assert proposal.review_state == "proposed"
        assert proposal.critique["redrafted"] is True
        assert proposal.confidence_score == 92

    asyncio.run(run())


def test_still_revise_after_the_redraft_budget_is_not_presented_as_reviewed_clean(client, monkeypatch):
    """A defect the critic named twice is still a defect. It must not land as `proposed`."""
    _mock_agent(monkeypatch, [(True, 90.0, "first"), (True, 90.0, "second")])
    _mock_critic(
        monkeypatch,
        [
            {"verdict": "revise", "issues": ["still concatenates"]},
            {"verdict": "revise", "issues": ["still concatenates"]},
        ],
    )

    async def run():
        f, job = await _seed()
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert proposal.can_fix is False
        assert proposal.review_state == "manual_review"
        assert proposal.critique["verdict"] == "reject"

    asyncio.run(run())


def test_reject_verdict_routes_to_manual_review(client, monkeypatch):
    agent = _mock_agent(monkeypatch, [(True, 95.0, "wrong")])
    _mock_critic(monkeypatch, [{"verdict": "reject", "reasoning": "does not fix the injection"}])

    async def run():
        f, job = await _seed()
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert agent["n"] == 1, "a reject must not spend a redraft"
        assert proposal.can_fix is False
        assert proposal.confidence_score == 0.0
        assert proposal.review_state == "manual_review"
        assert "does not fix the injection" in proposal.manual_review_reason

    asyncio.run(run())


def test_critic_outage_leaves_the_draft_intact(client, monkeypatch):
    """A critic failure must never cost the user their fix."""
    _mock_agent(monkeypatch, [(True, 90.0, "good")])

    async def boom(messages, **kwargs):
        raise llm_client.LLMTransientError("provider down")

    monkeypatch.setattr(llm_client, "get_completion", boom)

    async def run():
        f, job = await _seed()
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert proposal.can_fix is True
        assert proposal.confidence_score == 90.0
        assert proposal.review_state == "proposed"
        assert "skipped" in proposal.critique

    asyncio.run(run())


def test_critic_disabled_records_why_it_was_skipped(client, monkeypatch):
    _mock_agent(monkeypatch, [(True, 90.0, "good")])
    critic = _mock_critic(monkeypatch, [])
    monkeypatch.setattr(settings, "remediation_critic_enabled", False)

    async def run():
        f, job = await _seed()
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert critic["n"] == 0
        assert proposal.critique == {"skipped": "disabled"}
        assert proposal.confidence_score == 90.0

    asyncio.run(run())


def test_agent_declining_skips_the_critic(client, monkeypatch):
    """Nothing to critique when the drafter already said can_fix=false -- don't pay for it."""
    _mock_agent(monkeypatch, [(False, 0.0, None)])
    critic = _mock_critic(monkeypatch, [])

    async def run():
        f, job = await _seed()
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert critic["n"] == 0
        assert proposal.review_state == "manual_review"

    asyncio.run(run())


def test_reproposing_replaces_the_previous_proposal(client, monkeypatch):
    """Idempotent re-trigger, preserved through the refactor into _persist_proposal."""
    _mock_agent(monkeypatch, [(True, 90.0, "first"), (True, 70.0, "second")])
    _mock_critic(monkeypatch, [{"verdict": "pass"}, {"verdict": "pass"}])

    async def run():
        f, job = await _seed()
        await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        found = await AIFixProposal.find(AIFixProposal.finding_id == str(f.id)).to_list()
        assert len(found) == 1
        assert found[0].patched_code == "second"

    asyncio.run(run())


def test_sca_without_a_fixed_version_never_reaches_the_agent(client, monkeypatch):
    agent = _mock_agent(monkeypatch, [])
    _mock_critic(monkeypatch, [])

    async def run():
        dep = DependencyEmbedded(package="left-pad", installed_version="1.0.0")
        f, job = await _seed(file="package.json", kind="sca", dependency=dep)
        proposal = await ai_remediation_service._propose_for_finding(f, job, "main", "anthropic", "m")
        assert agent["n"] == 0
        assert "no safe version" in proposal.manual_review_reason

    asyncio.run(run())


# --- SCA context handed to the agent ---------------------------------------------------------


def test_sca_bundle_carries_the_target_version_for_the_agent(client):
    """Regression found in an E2E run: the scanner-reported fixed_version was computed only for the
    UI's version picker and never placed in the issue bundle, so on every dependency finding the
    model answered "no fixed version was specified by the scanner" and declined. SCA auto-fix could
    therefore never succeed."""
    async def run():
        dep = DependencyEmbedded(
            package="Flask", ecosystem="PyPI", installed_version="0.12.2",
            fixed_version="0.12.3", manifest="requirements.txt",
        )
        f, _ = await _seed(file="requirements.txt", kind="sca", dependency=dep)
        bundle = ai_remediation_service._issue_bundle(f, None)
        du = bundle["dependency_update"]
        assert du["recommended_version"] == "0.12.3"
        assert du["current_version"] == "0.12.2"
        assert du["package"] == "Flask"
        assert "0.12.3" in du["instruction"]
        assert "requirements.txt" in du["instruction"]

    asyncio.run(run())


def test_non_sca_bundle_has_no_dependency_section(client):
    """Keep the prompt lean: a SAST finding must not carry an empty dependency block."""
    async def run():
        f, _ = await _seed()
        assert "dependency_update" not in ai_remediation_service._issue_bundle(f, None)

    asyncio.run(run())


def test_absolute_manifest_from_legacy_findings_is_not_leaked(client):
    """An absolute clone path must not reach the prompt, the UI, or the PR body."""
    async def run():
        dep = DependencyEmbedded(
            package="Flask", installed_version="0.12.2", fixed_version="0.12.3",
            manifest=r"C:\Users\X\AppData\Local\Temp\zs-clones\zs-clone-abc\requirements.txt",
        )
        f, _ = await _seed(file="requirements.txt", kind="sca", dependency=dep)
        du = ai_remediation_service._issue_bundle(f, None)["dependency_update"]
        assert du["manifest"] == "requirements.txt"
        assert "zs-clones" not in du["instruction"]
        assert "AppData" not in du["instruction"]

    asyncio.run(run())


def test_absolute_manifest_with_no_relative_fallback_degrades_to_a_basename(client):
    async def run():
        dep = DependencyEmbedded(package="a", installed_version="1", fixed_version="2",
                                 manifest="/tmp/zs-clones/abc/sub/pom.xml")
        f, _ = await _seed(file="/tmp/zs-clones/abc/sub/pom.xml", kind="sca", dependency=dep)
        du = ai_remediation_service._issue_bundle(f, None)["dependency_update"]
        assert du["manifest"] == "pom.xml"

    asyncio.run(run())

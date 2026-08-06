"""Critique pass over a drafted fix. Mocks llm_client.get_completion so verdict handling, the
redraft loop, and the degradation path are exercised without a provider.

The load-bearing behaviours here: a reject can never reach a human as approvable, a pass can only
LOWER confidence, and a critic outage never turns into a fix outage.
"""

import asyncio

from app.core.config import settings
from app.services import llm_client, remediation_critic
from app.services.remediation_tools import SubmitFixProposalArgs

BUNDLE = {"finding_id": "f1", "rule_name": "SQL Injection", "location": {"file": "app.py"}}


def _draft(can_fix=True, confidence=90.0, original="a = q + uid", patched="a = q, (uid,)"):
    return SubmitFixProposalArgs(
        finding_id="f1", can_fix=can_fix, confidence_score=confidence, file_path="app.py",
        original_code=original if can_fix else None, patched_code=patched if can_fix else None,
        explanation="parameterize the query", patch_scope="single-file" if can_fix else "none",
    )


def _mock_completion(monkeypatch, payload):
    """payload may be a dict (always returned) or a list (returned in order, one per call)."""
    calls = {"n": 0, "messages": []}
    queue = list(payload) if isinstance(payload, list) else None

    async def fake(messages, **kwargs):
        calls["n"] += 1
        calls["messages"].append(messages)
        if queue is not None:
            return queue.pop(0) if queue else {"verdict": "pass"}
        return payload

    monkeypatch.setattr(llm_client, "get_completion", fake)
    return calls


def _critique(draft, **kw):
    return asyncio.run(
        remediation_critic.critique(BUNDLE, draft, project_id="p", scan_id="s", **kw)
    )


# --- verdict handling -----------------------------------------------------------------------


def test_pass_verdict_lowers_confidence_but_never_raises_it(monkeypatch):
    _mock_completion(monkeypatch, {"verdict": "pass", "adjusted_confidence": 70})
    result = _critique(_draft(confidence=90))
    assert result.normalized_verdict == "pass"

    applied = remediation_critic.apply_to_draft(_draft(confidence=90), result)
    assert applied.can_fix is True
    assert applied.confidence_score == 70  # critic lowered it


def test_a_generous_critic_cannot_inflate_confidence(monkeypatch):
    """The critic is a filter, not a promoter. A higher adjusted_confidence is ignored."""
    _mock_completion(monkeypatch, {"verdict": "pass", "adjusted_confidence": 99})
    result = _critique(_draft(confidence=55))
    applied = remediation_critic.apply_to_draft(_draft(confidence=55), result)
    assert applied.confidence_score == 55


def test_reject_verdict_makes_the_draft_unapprovable(monkeypatch):
    _mock_completion(
        monkeypatch,
        {"verdict": "reject", "reasoning": "Escapes output instead of parameterizing.",
         "issues": ["still concatenates uid"]},
    )
    result = _critique(_draft())
    applied = remediation_critic.apply_to_draft(_draft(), result)
    assert applied.can_fix is False
    assert applied.confidence_score == 0.0
    assert applied.patch_scope == "none"
    assert "parameterizing" in applied.explanation
    assert "still concatenates uid" in applied.explanation


def test_unknown_verdict_string_is_treated_as_pass(monkeypatch):
    """Tolerant boundary, like _FindingEnrichment: a model that invents a verdict word must not
    silently discard an otherwise good patch."""
    _mock_completion(monkeypatch, {"verdict": "looks-fine-to-me", "adjusted_confidence": 80})
    assert _critique(_draft()).normalized_verdict == "pass"


# --- not applicable / degradation -----------------------------------------------------------


def test_critic_skipped_when_disabled(monkeypatch):
    calls = _mock_completion(monkeypatch, {"verdict": "reject"})
    monkeypatch.setattr(settings, "remediation_critic_enabled", False)
    assert _critique(_draft()) is None
    assert calls["n"] == 0  # no tokens spent


def test_no_critique_for_a_draft_that_already_declined(monkeypatch):
    calls = _mock_completion(monkeypatch, {"verdict": "reject"})
    assert _critique(_draft(can_fix=False)) is None
    assert calls["n"] == 0


def test_provider_failure_degrades_to_none_not_an_exception(monkeypatch):
    async def boom(messages, **kwargs):
        raise llm_client.LLMTransientError("429 slow down")

    monkeypatch.setattr(llm_client, "get_completion", boom)
    assert _critique(_draft()) is None  # caller keeps the draft as drafted


def test_malformed_critic_json_degrades_to_none(monkeypatch):
    _mock_completion(monkeypatch, {"adjusted_confidence": "not-a-number"})
    assert _critique(_draft()) is None


def test_skipped_artifact_is_distinguishable_from_a_verdict():
    """The UI must be able to say 'not critiqued' rather than implying review passed."""
    assert remediation_critic.skipped("disabled") == {"skipped": "disabled"}


# --- prompt safety --------------------------------------------------------------------------


def test_patch_and_code_go_in_as_untrusted_context(monkeypatch):
    calls = _mock_completion(monkeypatch, {"verdict": "pass"})
    _critique(_draft(), file_excerpt="API_KEY = 'AKIAIOSFODNN7EXAMPLE'\nx = 1")
    user_msg = calls["messages"][0][1]["content"]
    assert "untrusted_context" in user_msg
    # The surrounding-file excerpt is repo content, so it is redacted like any other repo string.
    assert "AKIAIOSFODNN7EXAMPLE" not in user_msg


def test_revision_note_carries_the_concrete_issues():
    result = remediation_critic.CritiqueResult(
        verdict="revise", issues=["use a bound parameter", "keep the return type"], reasoning="close"
    )
    note = remediation_critic.revision_note_from(result)
    assert "use a bound parameter" in note
    assert "keep the return type" in note
    assert "same single file" in note

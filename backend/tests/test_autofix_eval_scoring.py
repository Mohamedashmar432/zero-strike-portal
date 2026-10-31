from app.services.remediation_tools import SubmitFixProposalArgs
from evals.autofix_eval import score

CASE = {"file": "app/db.py", "expect": {"can_fix": True, "must_not_contain": ["+ user_id"], "must_contain_any": ["%s", "?"]}}


def _p(**kw):
    base = dict(finding_id="c", can_fix=True, confidence_score=90, file_path="app/db.py",
                original_code="o", patched_code="cur.execute('... = %s', (user_id,))", explanation="e")
    return SubmitFixProposalArgs(**{**base, **kw})


def test_score_passes_a_correct_fix():
    assert score(CASE, _p()) == []


def test_score_flags_unfixed_wrong_file_and_declined():
    assert score(CASE, _p(patched_code="'...' + user_id")) != []
    assert score(CASE, _p(file_path="../etc/passwd")) == ["wrong file: ../etc/passwd"]
    assert score(CASE, _p(can_fix=False)) == ["can_fix=False, expected True"]

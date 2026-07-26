"""Regression test for llm_client._recover_rejected_tool_name -- the recovery for a real,
live-observed Groq/openai-gpt-oss-120b quirk: the model emits its answer as a tool call under a
synthetic name ("json") instead of a declared tool, and Groq's API rejects the WHOLE request
with a 400 even though the error body's `failed_generation` carries the exact intended tool
call. Uses the real error string captured from a live Groq response (see the AI Auto-Fix QA
pass), not a hypothetical shape."""

import json

from app.services.llm_client import _recover_rejected_tool_name

# Captured verbatim (finding_id/paths anonymized) from a real Groq openai/gpt-oss-120b response.
_REAL_GROQ_REJECTION = (
    "litellm.BadRequestError: GroqException - "
    '{"error":{"message":"Tool call validation failed: tool call validation failed: attempted to '
    "call tool 'json' which was not in request.tools\","
    '"type":"invalid_request_error","code":"tool_use_failed",'
    '"failed_generation":"{\\"name\\": \\"json\\", \\"arguments\\": {\\n  \\"can_fix\\": false,\\n  '
    '\\"confidence_score\\": 90,\\n  \\"explanation\\": \\"could not read the file\\",\\n  '
    '\\"file_path\\": \\"app/db.py\\",\\n  \\"finding_id\\": \\"real-test-1\\"\\n}}"}}'
)


def test_recovers_tool_call_from_real_groq_rejection_message():
    resp = _recover_rejected_tool_name(Exception(_REAL_GROQ_REJECTION))
    assert resp is not None
    assert resp.finish_reason == "tool_calls"
    assert resp.content is None
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.name == "json"
    args = json.loads(tc.arguments)
    assert args == {
        "can_fix": False,
        "confidence_score": 90,
        "explanation": "could not read the file",
        "file_path": "app/db.py",
        "finding_id": "real-test-1",
    }


def test_returns_none_for_unrelated_errors():
    assert _recover_rejected_tool_name(Exception("some other 400: bad request")) is None
    assert _recover_rejected_tool_name(Exception("GroqException - {not even json")) is None
    # Matches the trigger phrase but the JSON body doesn't have the expected shape.
    assert _recover_rejected_tool_name(Exception('attempted to call tool "x" {"error": {}}')) is None
